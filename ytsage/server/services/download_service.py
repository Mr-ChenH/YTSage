"""Download command construction and progress parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from ..models import CreateTaskRequest, TaskProgress
from .dependencies import ffmpeg_location_arg, ytdlp_command

_PROGRESS_RE = re.compile(
    r"\[download\]\s+(?P<percent>\d+(?:\.\d+)?)%.*?(?:at\s+(?P<speed>\S+))?.*?(?:ETA\s+(?P<eta>\S+))?"
)
_DEST_RE = re.compile(r"\[download\]\s+Destination:\s+(?P<path>.+)")
_MERGE_RE = re.compile(r"\[Merger\]\s+Merging formats into\s+\"(?P<path>.+)\"")
_PLAYLIST_ITEM_RE = re.compile(r"\[download\]\s+Downloading item\s+(?P<index>\d+)\s+of\s+(?P<total>\d+)")
_PLAYLIST_FINISHED_RE = re.compile(r"\[download\]\s+Finished downloading playlist:")
_ERROR_RE = re.compile(r"ERROR:\s+(?P<message>.+)")



def build_download_command(request: CreateTaskRequest, download_dir: Path) -> list[str]:
    cmd = [*ytdlp_command(), request.url, "--newline", "--progress", "--encoding", "utf-8", "-P", str(download_dir), "-o", request.filename_template]
    ffmpeg_location = ffmpeg_location_arg()
    if ffmpeg_location:
        cmd.extend(["--ffmpeg-location", ffmpeg_location])

    if request.format_id:
        if request.playlist_items:
            cmd.extend(["-f", f"{request.format_id}/bestvideo*+bestaudio/best"])
        else:
            cmd.extend(["-f", request.format_id])
    elif request.mode == "audio":
        cmd.extend(["-f", "bestaudio/best"])

    if request.mode == "audio":
        cmd.extend(["-x", "--audio-format", request.audio_format])
        if request.audio_normalization:
            cmd.extend(["--postprocessor-args", "ffmpeg:-filter:a loudnorm=I=-16:LRA=11:TP=-1.5"])
    elif request.output_format:
        cmd.extend(["--merge-output-format", request.output_format])

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
        failed_indexes = list(progress.playlist_failed_indexes)
        if progress.playlist_current_index is not None and progress.playlist_current_index not in failed_indexes:
            failed_indexes.append(progress.playlist_current_index)
        progress.playlist_failed_indexes = failed_indexes
        failures = dict(progress.playlist_failures)
        if progress.playlist_current_index is not None:
            failures[str(progress.playlist_current_index)] = error.group("message").strip()
        progress.playlist_failures = failures
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
        if match.group("speed"):
            progress.speed = match.group("speed")
        if match.group("eta"):
            progress.eta = match.group("eta")
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
