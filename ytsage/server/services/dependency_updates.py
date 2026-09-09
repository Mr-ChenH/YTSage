"""Dependency version checks and observable background updates."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.request
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Callable

from packaging.version import InvalidVersion, Version

from .dependencies import clear_dependency_cache, get_ffmpeg_info, get_ytdlp_info


@dataclass
class DependencyStatus:
    name: str
    current_version: str | None
    latest_version: str | None = None
    update_available: bool = False
    managed: bool = True
    source: str | None = None
    error: str | None = None


class DependencyUpdateManager:
    def __init__(self, latest_version: Callable[[str], str] | None = None) -> None:
        self._latest_version = latest_version or _pypi_latest_version
        self._lock = threading.RLock()
        self._running = False
        self._phase = "idle"
        self._logs: list[str] = []
        self._error: str | None = None
        self._dependencies: list[DependencyStatus] = []

    def status(self, refresh: bool = False) -> dict[str, object]:
        with self._lock:
            needs_refresh = refresh and not self._running
        if needs_refresh:
            self.check()
        with self._lock:
            return {
                "running": self._running,
                "phase": self._phase,
                "dependencies": [asdict(item) for item in self._dependencies],
                "logs": self._logs.copy(),
                "error": self._error,
            }

    def start_check(self) -> dict[str, object]:
        with self._lock:
            if self._running:
                return self.status()
            self._running = True
            self._phase = "checking"
            self._logs = ["Checking installed dependency versions..."]
            self._error = None
        threading.Thread(target=self._check_in_background, name="dependency-check", daemon=True).start()
        return self.status()

    def _check_in_background(self) -> None:
        try:
            self._finish_check()
        finally:
            with self._lock:
                self._running = False

    def check(self) -> dict[str, object]:
        with self._lock:
            if self._running:
                return self.status()
            self._running = True
            self._phase = "checking"
            self._logs = ["Checking installed dependency versions..."]
            self._error = None
        try:
            self._finish_check()
        finally:
            with self._lock:
                self._running = False
        return self.status()

    def _finish_check(self) -> None:
        try:
            dependencies = self._collect_status()
            with self._lock:
                self._dependencies = dependencies
                if any(item.update_available for item in dependencies):
                    self._logs.append("Updates are available.")
                else:
                    self._logs.append("All application-managed dependencies are current.")
                self._phase = "ready"
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
                self._logs.append(f"Version check failed: {exc}")
                self._phase = "failed"

    def start_update(self) -> dict[str, object]:
        with self._lock:
            if self._running:
                return self.status()
            self._running = True
            self._phase = "updating"
            self._logs = ["Starting dependency update..."]
            self._error = None
        threading.Thread(target=self._update, name="dependency-update", daemon=True).start()
        return self.status()

    def _collect_status(self) -> list[DependencyStatus]:
        ytdlp = get_ytdlp_info()
        ffmpeg = get_ffmpeg_info()
        items = [self._package_status("yt-dlp", "yt-dlp", ytdlp.version if ytdlp else None, ytdlp.source if ytdlp else None)]
        if ffmpeg is None:
            items.append(DependencyStatus(name="ffmpeg", current_version=None, managed=False, source=None, error="not found"))
        elif ffmpeg.source == "imageio-ffmpeg":
            items.append(self._package_status("ffmpeg", "imageio-ffmpeg", ffmpeg.version, ffmpeg.source))
        else:
            items.append(DependencyStatus(name="ffmpeg", current_version=_display_ffmpeg_version(ffmpeg.version), managed=False, source=ffmpeg.source))
        return items

    def _package_status(self, name: str, package: str, current: str | None, source: str | None) -> DependencyStatus:
        try:
            latest = self._latest_version(package)
            return DependencyStatus(name=name, current_version=current, latest_version=latest, update_available=_is_newer(latest, current), source=source)
        except Exception as exc:
            return DependencyStatus(name=name, current_version=current, managed=True, source=source, error=str(exc))

    def _update(self) -> None:
        try:
            dependencies = self._collect_status()
            for item in dependencies:
                if not item.managed:
                    self._append_log(f"{item.name}: managed by the system or container; skipped.")
                    continue
                if item.current_version and item.latest_version and not item.update_available:
                    self._append_log(f"{item.name}: already current ({item.current_version}); skipped.")
                    continue
                package = "yt-dlp" if item.name == "yt-dlp" else "imageio-ffmpeg"
                target = f" to {item.latest_version}" if item.latest_version else ""
                self._append_log(f"{item.name}: updating from {item.current_version or 'not installed'}{target}...")
                self._run_pip(package)
                self._append_log(f"{item.name}: update command completed.")
            clear_dependency_cache()
            updated = self._collect_status()
            with self._lock:
                self._dependencies = updated
                self._phase = "completed"
                self._logs.append("Dependency update finished.")
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
                self._phase = "failed"
                self._logs.append(f"Dependency update failed: {exc}")
        finally:
            with self._lock:
                self._running = False

    def _run_pip(self, package: str) -> None:
        process = subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "--upgrade", package],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            text = line.strip()
            if text:
                self._append_log(text)
        if process.wait() != 0:
            raise RuntimeError(f"pip failed while updating {package}")

    def _append_log(self, message: str) -> None:
        with self._lock:
            self._logs.append(message)
            self._logs = self._logs[-200:]


def _display_ffmpeg_version(version: str) -> str:
    prefix = "ffmpeg version "
    if version.lower().startswith(prefix):
        return version[len(prefix):].split()[0]
    return version


def _is_newer(latest: str | None, current: str | None) -> bool:
    if not latest or not current:
        return bool(latest and not current)
    try:
        return Version(latest) > Version(current)
    except InvalidVersion:
        return latest != current


def _pypi_latest_version(package: str) -> str:
    url = f"https://pypi.org/pypi/{package}/json"
    with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310 - fixed PyPI host
        payload = json.load(response)
    version = payload.get("info", {}).get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError(f"PyPI returned no version for {package}")
    return version
