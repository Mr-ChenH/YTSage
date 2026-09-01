"""Runtime dependency detection and lightweight auto-installation."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from loguru import logger


@dataclass(frozen=True)
class CommandInfo:
    command: list[str]
    version: str
    source: str


def auto_install_enabled() -> bool:
    return os.environ.get("YTSAGE_AUTO_INSTALL_DEPS", "1").lower() not in {"0", "false", "no", "off"}


def ensure_runtime_dependencies() -> None:
    """Install Python-level runtime dependencies that can be safely self-installed."""
    if not auto_install_enabled():
        logger.info("Runtime dependency auto-install is disabled")
        return
    ensure_ytdlp()
    ensure_ffmpeg()


def update_runtime_dependencies() -> dict[str, str]:
    """Upgrade managed runtime dependencies and refresh cached command info."""
    results: dict[str, str] = {}
    results["yt_dlp"] = "updated" if _pip_install("yt-dlp --upgrade", timeout=240) else "failed"
    results["ffmpeg"] = "updated" if _pip_install("imageio-ffmpeg --upgrade", timeout=300) else "failed"
    clear_dependency_cache()
    ytdlp = get_ytdlp_info()
    ffmpeg = get_ffmpeg_info()
    if ytdlp is not None:
        results["yt_dlp_version"] = ytdlp.version
    if ffmpeg is not None:
        results["ffmpeg_version"] = ffmpeg.version
    return results


def ensure_ytdlp() -> CommandInfo | None:
    info = get_ytdlp_info()
    if info is not None:
        return info
    logger.warning("yt-dlp was not found; attempting automatic installation with pip")
    if not _pip_install("yt-dlp", timeout=180):
        return None
    logger.info("yt-dlp installed successfully")
    return get_ytdlp_info()


def ensure_ffmpeg() -> CommandInfo | None:
    info = get_ffmpeg_info()
    if info is not None:
        return info
    logger.warning("ffmpeg was not found; attempting automatic installation with imageio-ffmpeg")
    if not _pip_install("imageio-ffmpeg", timeout=240):
        return None
    clear_dependency_cache()
    info = get_ffmpeg_info()
    if info is not None:
        logger.info("ffmpeg installed successfully via imageio-ffmpeg")
    return info


@lru_cache(maxsize=1)
def get_ytdlp_info() -> CommandInfo | None:
    executable = shutil.which("yt-dlp")
    if executable:
        version = _version([executable, "--version"])
        if version != "error":
            return CommandInfo(command=[executable], version=version, source="cli")
    if importlib.util.find_spec("yt_dlp") is not None:
        version = _version([sys.executable, "-m", "yt_dlp", "--version"])
        if version != "error":
            return CommandInfo(command=[sys.executable, "-m", "yt_dlp"], version=version, source="python-module")
    return None


@lru_cache(maxsize=1)
def get_ffmpeg_info() -> CommandInfo | None:
    executable = shutil.which("ffmpeg")
    if executable:
        version = _version([executable, "-version"])
        if version != "error":
            return CommandInfo(command=[executable], version=version, source="cli")

    if importlib.util.find_spec("imageio_ffmpeg") is not None:
        try:
            import imageio_ffmpeg

            ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception as exc:
            logger.warning("imageio-ffmpeg is installed but no ffmpeg executable was available: {}", exc)
            return None
        version = _version([ffmpeg_path, "-version"])
        if version != "error":
            return CommandInfo(command=[ffmpeg_path], version=version, source="imageio-ffmpeg")
    return None


def ytdlp_command() -> list[str]:
    info = get_ytdlp_info() or ensure_ytdlp()
    if info is None:
        return ["yt-dlp"]
    return info.command.copy()


def ytdlp_base_command() -> list[str]:
    command = ytdlp_command()
    deno = shutil.which("deno")
    if deno:
        command.extend(["--js-runtimes", f"deno:{deno}"])
    return command


def ytdlp_version() -> str:
    info = get_ytdlp_info() or ensure_ytdlp()
    return info.version if info is not None else "not found"


def ffmpeg_version() -> str:
    info = get_ffmpeg_info() or ensure_ffmpeg()
    return info.version if info is not None else "not found"


def ffmpeg_location_arg() -> str | None:
    info = get_ffmpeg_info() or ensure_ffmpeg()
    if info is None:
        return None
    executable = Path(info.command[0])
    return str(executable.parent if info.source == "imageio-ffmpeg" else executable)


def clear_dependency_cache() -> None:
    get_ytdlp_info.cache_clear()
    get_ffmpeg_info.cache_clear()


def _pip_install(package: str, timeout: int) -> bool:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", *package.split()],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    clear_dependency_cache()
    if result.returncode != 0:
        logger.error("Automatic installation failed for {}: {}", package, result.stderr.strip() or result.stdout.strip())
        return False
    return True


def _version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except Exception:
        return "error"
    if result.returncode != 0:
        return "error"
    output = result.stdout.strip() or result.stderr.strip()
    return output.splitlines()[0].strip() if output else "unknown"
