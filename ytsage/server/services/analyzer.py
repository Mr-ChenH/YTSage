"""Generic yt-dlp analysis orchestration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import requests
from fastapi import HTTPException, status

from ..analyzers import bilibili
from ..models import AnalyzeRequest, AnalyzeResponse, FormatInfo, PlaylistEntry, SubtitleInfo
from .cookies import cookie_file_for_url
from .dependencies import ytdlp_base_command


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _string_map(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _format_type(item: dict[str, Any]) -> str:
    vcodec, acodec = item.get("vcodec"), item.get("acodec")
    if vcodec and vcodec != "none" and acodec and acodec != "none":
        return "video+audio"
    if vcodec and vcodec != "none":
        return "video"
    if acodec and acodec != "none":
        return "audio"
    return "unknown"


def _formats_from(items: Any) -> list[FormatInfo]:
    return [
        FormatInfo(
            format_id=str(item.get("format_id") or ""),
            ext=_as_str(item.get("ext")),
            resolution=_as_str(item.get("resolution")) or (f"{item.get('width')}x{item.get('height')}" if item.get("width") and item.get("height") else None),
            video_codec=_as_str(item.get("vcodec")),
            audio_codec=_as_str(item.get("acodec")),
            fps=_as_float(item.get("fps")),
            filesize=_as_int(item.get("filesize") or item.get("filesize_approx")),
            type=_format_type(item),
        )
        for item in _as_dict_list(items)
        if item.get("format_id")
    ]


def _best_thumbnail(data: dict[str, Any]) -> str | None:
    thumbnail = _as_str(data.get("thumbnail"))
    if thumbnail:
        return thumbnail
    candidates = [item for item in _as_dict_list(data.get("thumbnails")) if _as_str(item.get("url"))]
    candidates.sort(key=lambda item: (_as_float(item.get("width")) or 0) * (_as_float(item.get("height")) or 0), reverse=True)
    return _as_str(candidates[0].get("url")) if candidates else None


def _entry_url_from_item(item: dict[str, Any]) -> str | None:
    webpage_url = _as_str(item.get("webpage_url")) or _as_str(item.get("original_url"))
    if webpage_url:
        return webpage_url
    url = _as_str(item.get("url"))
    if not url:
        return None
    if url.startswith(("http://", "https://")):
        return url
    return f"https://www.bilibili.com/video/{url}/" if url.startswith("BV") else None


def _playlist_entry(index: int, item: dict[str, Any]) -> PlaylistEntry:
    entry_url = _entry_url_from_item(item)
    return PlaylistEntry(index=index, id=_as_str(item.get("id")) or _as_str(item.get("url")), title=_as_str(item.get("title")), url=entry_url, webpage_url=entry_url, duration=_as_float(item.get("duration")), channel=_as_str(item.get("channel") or item.get("uploader")), thumbnail_url=_best_thumbnail(item))


def _formats_from_single_entry(url: str | None, cookie_file: Path | None, timeout: int) -> list[FormatInfo]:
    if not url:
        return []
    cmd = [*ytdlp_base_command(), "--dump-single-json", "--no-warnings", "--skip-download", "--no-playlist"]
    if cookie_file is not None:
        cmd.extend(["--cookies", str(cookie_file)])
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    try:
        return _formats_from(json.loads(result.stdout).get("formats"))
    except json.JSONDecodeError:
        return []


# Compatibility wrappers retained for existing imports and tests.
def _is_bilibili_url(url: str) -> bool:
    return bilibili.is_bilibili_url(url)


def _bilibili_collection_from_api(url: str, cookie_file: Path | None = None, timeout: int = 15) -> tuple[str | None, list[PlaylistEntry]]:
    return bilibili.collection_from_api(url, cookie_file, timeout, requests)


def _bilibili_entries_from_season(season: Any) -> tuple[str | None, list[PlaylistEntry]]:
    return bilibili.entries_from_season(season)


def _bilibili_collection_entries(url: str, cookie_file: Path | None = None, timeout: int = 15) -> tuple[str | None, list[PlaylistEntry], str | None]:
    return bilibili.collection_entries(url, cookie_file, timeout, requests)


def _subtitles_from(data: dict[str, Any]) -> list[SubtitleInfo]:
    subtitles: list[SubtitleInfo] = []
    for automatic, source in ((False, _string_map(data.get("subtitles"))), (True, _string_map(data.get("automatic_captions")))):
        for language, entries in source.items():
            subtitles.append(SubtitleInfo(language=str(language), name=str(language), automatic=automatic, formats=sorted({str(entry.get("ext")) for entry in _as_dict_list(entries) if entry.get("ext")})))
    return subtitles


def analyze(request: AnalyzeRequest, timeout: int = 60, config_dir: Path | None = None) -> AnalyzeResponse:
    cmd = [*ytdlp_base_command(), "--dump-single-json", "--flat-playlist", "--no-warnings", "--skip-download"]
    cookie_file = cookie_file_for_url(config_dir, request.url) if config_dir is not None else None
    if cookie_file is not None:
        cmd.extend(["--cookies", str(cookie_file)])
    if request.generic_mode:
        cmd.append("--ignore-no-formats-error")
    cmd.append(request.url)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="yt-dlp is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="URL analysis timed out") from exc
    if result.returncode != 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.stderr.strip() or result.stdout.strip() or "yt-dlp analysis failed")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="yt-dlp returned invalid JSON") from exc

    raw: dict[str, Any] = {key: _as_str(data.get(key)) for key in ("extractor", "extractor_key", "webpage_url", "original_url", "display_id")}
    entries = data.get("entries")
    entry_items = _as_dict_list(entries)
    is_playlist = isinstance(entries, list)
    playlist_entries = [_playlist_entry(index, item) for index, item in enumerate(entry_items, start=1)]

    collection_title = collection_cover = None
    if _is_bilibili_url(request.url):
        collection_title, collection_entries, collection_cover = _bilibili_collection_entries(request.url, cookie_file)
        if collection_entries:
            playlist_entries, is_playlist = collection_entries, True
            raw["playlist_source"] = "bilibili_ugc_season"
            if collection_title:
                raw["collection_title"] = collection_title
            if collection_cover:
                raw["collection_cover"] = collection_cover

    formats = _formats_from(data.get("formats", []))
    if not formats and is_playlist:
        for item in entry_items:
            formats = _formats_from(item.get("formats"))
            if formats:
                raw["formats_source"] = "first_playlist_entry"
                break
    if not formats and is_playlist and entry_items:
        formats = _formats_from_single_entry(_entry_url_from_item(entry_items[0]), cookie_file, min(timeout, 30))
        if formats:
            raw["formats_source"] = "first_playlist_entry_probe"
    if not formats:
        raw["warning_code"] = raw["warning"] = "metadata_without_formats"
        formats = [FormatInfo(format_id="best", ext=_as_str(data.get("ext")), resolution=_as_str(data.get("resolution")) or "best", type="video+audio"), FormatInfo(format_id="bestaudio", type="audio")]

    thumbnail_url = collection_cover or _best_thumbnail(data)
    if not thumbnail_url and is_playlist:
        for item in entry_items:
            thumbnail_url = _best_thumbnail(item)
            if thumbnail_url:
                raw["thumbnail_source"] = "first_playlist_entry"
                break

    return AnalyzeResponse(url=request.url, title=collection_title or _as_str(data.get("title")), channel=_as_str(data.get("channel") or data.get("uploader")), duration=_as_float(data.get("duration")), thumbnail_url=thumbnail_url, is_playlist=is_playlist, playlist_count=len(playlist_entries) if is_playlist else None, playlist_entries=playlist_entries, formats=formats, subtitles=_subtitles_from(data), raw=raw)
