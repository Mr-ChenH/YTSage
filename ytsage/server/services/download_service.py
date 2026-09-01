"""Download command construction and progress parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from ..models import CreateTaskRequest, TaskProgress
from .dependencies import ffmpeg_location_arg, ytdlp_base_command

_PROGRESS_RE = re.compile(r"\[download\]\s+(?P<percent>\d+(?:\.\d+)?)%")
_SPEED_RE = re.compile(r"\bat\s+(?P<speed>\S+/s)\b")
_ETA_RE = re.compile(r"\bETA\s+(?P<eta>\S+)")
_DEST_RE = re.compile(r"\[download\]\s+Destination:\s+(?P<path>.+)")
_MERGE_RE = re.compile(r"\[Merger\]\s+Merging formats into\s+\"(?P<path>.+)\"")
_PLAYLIST_ITEM_RE = re.compile(r"\[download\]\s+Downloading item\s+(?P<index>\d+)\s+of\s+(?P<total>\d+)")
_PLAYLIST_FINISHED_RE = re.compile(r"\[download\]\s+Finished downloading playlist:")
_ERROR_RE = re.compile(r"ERROR:\s+(?P<message>.+)")


def _is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("youtube.com") or host.endswith("youtu.be")



def _single_item_filename_template(request: CreateTaskRequest) -> str:
    template = request.filename_template
    is_playlist = bool(request.playlist_entries or request.playlist_items)
    if is_playlist or "%(playlist_" in template:
        return template
    normalized = template.replace("\\", "/").lstrip("./")
    if normalized.startswith("%(title)s/"):
        return template
    return f"%(title)s/{template}"


def build_download_command(
    request: CreateTaskRequest,
    download_dir: Path,
    *,
    single_item_directory: bool | None = None,
) -> list[str]:
    if single_item_directory is None:
        single_item_directory = not bool(request.playlist_entries or request.playlist_items or "%(playlist_" in request.filename_template)
    output_template = _single_item_filename_template(request) if single_item_directory else request.filename_template
    cmd = [*ytdlp_base_command(), request.url, "--newline", "--progress", "--encoding", "utf-8", "-P", str(download_dir), "-o", output_template]
    ffmpeg_location = ffmpeg_location_arg()
    if ffmpeg_location:
        cmd.extend(["--ffmpeg-location", ffmpeg_location])
    if _is_youtube_url(request.url):
        cmd.extend(
            [
                "--remote-components",
                "ejs:github",
                "--http-chunk-size",
                "2M",
                "--socket-timeout",
                "45",
                "--retries",
                "5",
                "--retry-sleep",
                "http:exp=1:8",
            ]
        )
        if request.format_id == "18":
            cmd.extend(["--extractor-args", "youtube:player_client=android"])

    if request.format_id:
        if request.mode == "video" and request.format_id != "18":
            cmd.extend(["-f", f"{request.format_id}+bestaudio/{request.format_id}/bestvideo*+bestaudio/best"])
        else:
            cmd.extend(["-f", request.format_id])
    elif request.mode == "audio":
        cmd.extend(["-f", "bestaudio/best"])
    elif request.mode == "video":
        cmd.extend(["-f", "bestvideo*+bestaudio/best"])

    if request.mode == "audio":
        cmd.extend(["-x", "--audio-format", request.audio_format])
        if request.audio_normalization:
            cmd.extend(["--postprocessor-args", "ffmpeg:-filter:a loudnorm=I=-16:LRA=11:TP=-1.5"])
    elif request.output_format:
        cmd.extend(["--merge-output-format", request.output_format, "--remux-video", request.output_format])

    if request.subtitle_langs:
        cmd.extend(["--write-subs", "--sub-langs", ",".join(request.subtitle_langs)])
        if request.merge_subtitles:
            cmd.append("--embed-subs")

    if request.save_thumbnail:
        cmd.append("--write-thumbnail")
    if request.save_description:
        cmd.append("--write-description")
    if request.embed_chapters:
        cmd.append("--embed-chapters")
    if request.rate_limit:
        cmd.extend(["--limit-rate", request.rate_limit])
    if request.proxy_url:
        cmd.extend(["--proxy", request.proxy_url])
    if request.concurrent_fragments:
        cmd.extend(["--concurrent-fragments", str(request.concurrent_fragments)])
    if request.cookie_file:
        cmd.extend(["--cookies", request.cookie_file])
    if request.playlist_items:
        cmd.extend(["--playlist-items", request.playlist_items])
        cmd.append("--ignore-errors")

    return cmd


def parse_progress_line(line: str, current: TaskProgress | None = None) -> TaskProgress:
    progress = current or TaskProgress()
    stripped = line.strip()

    playlist_item = _PLAYLIST_ITEM_RE.search(stripped)
    if playlist_item:
        progress.playlist_current_index = int(playlist_item.group("index"))
        progress.playlist_last_index = progress.playlist_current_index
        progress.playlist_total = int(playlist_item.group("total"))
        progress.status_text = stripped
        return progress

    if _PLAYLIST_FINISHED_RE.search(stripped):
        progress.playlist_current_index = None
        progress.status_text = stripped
        return progress

    error = _ERROR_RE.search(stripped)
    if error:
        progress.status_text = stripped
        return progress

    destination = _DEST_RE.search(line) or _MERGE_RE.search(line)
    if destination:
        progress.current_filename = destination.group("path").strip()
        progress.status_text = line.strip()
        return progress

    match = _PROGRESS_RE.search(line)
    if match:
        progress.percent = float(match.group("percent"))
        speed = _SPEED_RE.search(line)
        eta = _ETA_RE.search(line)
        if speed:
            progress.speed = speed.group("speed")
        if eta:
            progress.eta = eta.group("eta")
        progress.status_text = line.strip()
        return progress

    if stripped:
        progress.status_text = stripped
    return progress


def discover_new_files(download_dir: Path, before: set[Path]) -> list[Path]:
    after = {path for path in download_dir.rglob("*") if path.is_file() and path.suffix != ".part"}
    return sorted(after - before, key=lambda path: path.stat().st_mtime, reverse=True)


def snapshot_files(download_dir: Path) -> set[Path]:
    return {path for path in download_dir.rglob("*") if path.is_file()}
