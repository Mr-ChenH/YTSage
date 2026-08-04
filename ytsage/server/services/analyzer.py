"""yt-dlp analysis service."""

from __future__ import annotations

import http.cookiejar
import json
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from fastapi import HTTPException, status

from ..models import AnalyzeRequest, AnalyzeResponse, FormatInfo, PlaylistEntry, SubtitleInfo
from .cookies import cookie_file_for_url
from .dependencies import ytdlp_command


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
    if number is None:
        return None
    return int(number)


def _as_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_map(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _format_type(item: dict[str, Any]) -> str:
    vcodec = item.get("vcodec")
    acodec = item.get("acodec")
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
    if not candidates:
        return None
    candidates.sort(key=lambda item: (_as_float(item.get("width")) or 0) * (_as_float(item.get("height")) or 0), reverse=True)
    return _as_str(candidates[0].get("url"))


def _entry_url_from_item(item: dict[str, Any]) -> str | None:
    webpage_url = _as_str(item.get("webpage_url")) or _as_str(item.get("original_url"))
    if webpage_url:
        return webpage_url
    url = _as_str(item.get("url"))
    if not url:
        return None
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("BV"):
        return f"https://www.bilibili.com/video/{url}/"
    return None


def _playlist_entry(index: int, item: dict[str, Any]) -> PlaylistEntry:
    entry_url = _entry_url_from_item(item)
    return PlaylistEntry(
        index=index,
        id=_as_str(item.get("id")) or _as_str(item.get("url")),
        title=_as_str(item.get("title")),
        url=entry_url,
        webpage_url=entry_url,
        duration=_as_float(item.get("duration")),
        channel=_as_str(item.get("channel") or item.get("uploader")),
        thumbnail_url=_best_thumbnail(item),
    )


def _formats_from_single_entry(url: str | None, cookie_file: Path | None, timeout: int) -> list[FormatInfo]:
    if not url:
        return []
    cmd = [*ytdlp_command(), "--dump-single-json", "--no-warnings", "--skip-download", "--no-playlist"]
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
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    return _formats_from(data.get("formats"))


def _bilibili_space_list_params(url: str) -> tuple[str, str] | None:
    match = re.search(r"space\.bilibili\.com/(\d+)/lists/(\d+)", url)
    if not match:
        return None
    return match.group(1), match.group(2)


def _bilibili_json_response(response: requests.Response) -> dict[str, Any] | None:
    try:
        return json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _bilibili_space_collection_entries(url: str, cookie_file: Path | None = None, timeout: int = 15) -> tuple[str | None, list[PlaylistEntry], str | None]:
    params = _bilibili_space_list_params(url)
    if not params:
        return None, [], None
    mid, season_id = params
    entries: list[PlaylistEntry] = []
    collection_title: str | None = None
    collection_cover: str | None = None
    page_num = 1
    page_size = 100
    while True:
        try:
            response = requests.get(
                "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list",
                params={"mid": mid, "season_id": season_id, "page_num": page_num, "page_size": page_size},
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                    "Referer": url,
                },
                cookies=_load_cookie_jar(cookie_file),
                timeout=timeout,
            )
        except requests.RequestException:
            break
        if response.status_code >= 400:
            break
        payload = _bilibili_json_response(response)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            break
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        collection_title = collection_title or _as_str(meta.get("title")) or _as_str(meta.get("name"))
        collection_cover = collection_cover or _as_str(meta.get("cover"))
        archives = _as_dict_list(data.get("archives"))
        for archive in archives:
            bvid = _as_str(archive.get("bvid"))
            aid = _as_str(archive.get("aid"))
            entry_url = f"https://www.bilibili.com/video/{bvid}" if bvid else None
            entries.append(
                PlaylistEntry(
                    index=len(entries) + 1,
                    id=bvid or aid,
                    title=_as_str(archive.get("title")),
                    url=entry_url,
                    webpage_url=entry_url,
                    duration=_as_float(archive.get("duration")),
                    channel=None,
                    thumbnail_url=_as_str(archive.get("pic")),
                )
            )
        page = data.get("page") if isinstance(data.get("page"), dict) else {}
        total = _as_int(page.get("total")) or len(entries)
        if len(entries) >= total or not archives:
            break
        page_num += 1
        if page_num > 20:
            break
    return collection_title, entries, collection_cover


def _bilibili_bvid_from_url(url: str) -> str | None:
    match = re.search(r"/(BV[0-9A-Za-z]+)/?", url)
    if match:
        return match.group(1)
    return None


def _is_bilibili_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("bilibili.com") or host.endswith("b23.tv")


def _extract_balanced_json(text: str, marker: str) -> dict[str, Any] | None:
    start = text.find(marker)
    if start < 0:
        return None
    start = text.find("{", start)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _load_cookie_jar(cookie_file: Path | None) -> http.cookiejar.MozillaCookieJar | None:
    if cookie_file is None or not cookie_file.is_file():
        return None
    jar = http.cookiejar.MozillaCookieJar(str(cookie_file))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:
        return None
    return jar


def _bilibili_episode_title(episode: dict[str, Any]) -> str | None:
    arc = episode.get("arc") if isinstance(episode.get("arc"), dict) else {}
    title = (
        _as_str(episode.get("title"))
        or _as_str(episode.get("long_title"))
        or _as_str(episode.get("part"))
        or _as_str(arc.get("title"))
    )
    page = _as_int(episode.get("page"))
    if title:
        return title
    if page:
        return f"P{page}"
    return None


def _bilibili_collection_from_api(url: str, cookie_file: Path | None = None, timeout: int = 15) -> tuple[str | None, list[PlaylistEntry]]:
    bvid = _bilibili_bvid_from_url(url)
    if not bvid:
        return None, []
    try:
        response = requests.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                "Referer": url,
            },
            cookies=_load_cookie_jar(cookie_file),
            timeout=timeout,
        )
    except requests.RequestException:
        return None, []
    if response.status_code >= 400:
        return None, []
    try:
        payload = _bilibili_json_response(response)
    except ValueError:
        return None, []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None, []
    return _bilibili_entries_from_season(data.get("ugc_season"))


def _bilibili_entries_from_season(season: Any) -> tuple[str | None, list[PlaylistEntry]]:
    if not isinstance(season, dict):
        return None, []
    collection_title = _as_str(season.get("title"))
    entries: list[PlaylistEntry] = []
    for section in _as_dict_list(season.get("sections")):
        for episode in _as_dict_list(section.get("episodes")):
            bvid = _as_str(episode.get("bvid")) or _as_str(episode.get("bvid_str"))
            aid = _as_str(episode.get("aid"))
            page = _as_int(episode.get("page"))
            entry_url = f"https://www.bilibili.com/video/{bvid}/" if bvid else None
            if entry_url and page and page > 1:
                entry_url = f"{entry_url}?p={page}"
            entries.append(
                PlaylistEntry(
                    index=len(entries) + 1,
                    id=bvid or aid,
                    title=_bilibili_episode_title(episode),
                    url=entry_url,
                    webpage_url=entry_url,
                    duration=_as_float(episode.get("duration")) or _as_float(episode.get("arc", {}).get("duration") if isinstance(episode.get("arc"), dict) else None),
                    channel=None,
                    thumbnail_url=_as_str(episode.get("cover")) or _as_str(episode.get("arc", {}).get("pic") if isinstance(episode.get("arc"), dict) else None),
                )
            )
    return collection_title, entries


def _bilibili_collection_entries(url: str, cookie_file: Path | None = None, timeout: int = 15) -> tuple[str | None, list[PlaylistEntry], str | None]:
    collection_title, entries, collection_cover = _bilibili_space_collection_entries(url, cookie_file=cookie_file, timeout=timeout)
    if entries:
        return collection_title, entries, collection_cover
    if not _is_bilibili_url(url):
        return None, [], None
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
                "Referer": "https://www.bilibili.com/",
            },
            cookies=_load_cookie_jar(cookie_file),
            timeout=timeout,
        )
    except requests.RequestException:
        return None, []
    if response.status_code >= 400:
        return None, []

    state = _extract_balanced_json(response.text, "window.__INITIAL_STATE__=")
    if not state:
        return (*_bilibili_collection_from_api(url, cookie_file=cookie_file, timeout=timeout), None)
    collection_title, entries = _bilibili_entries_from_season(state.get("ugc_season") or state.get("ugcSeason"))
    if entries:
        return collection_title, entries, None
    return (*_bilibili_collection_from_api(url, cookie_file=cookie_file, timeout=timeout), None)


def analyze(request: AnalyzeRequest, timeout: int = 60, config_dir: Path | None = None) -> AnalyzeResponse:
    cmd = [*ytdlp_command(), "--dump-single-json", "--flat-playlist", "--no-warnings", "--skip-download"]
    cookie_file: Path | None = None
    if config_dir is not None:
        cookie_file = cookie_file_for_url(config_dir, request.url)
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
        detail = result.stderr.strip() or result.stdout.strip() or "yt-dlp analysis failed"
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="yt-dlp returned invalid JSON") from exc

    raw: dict[str, Any] = {
        "extractor": _as_str(data.get("extractor")),
        "extractor_key": _as_str(data.get("extractor_key")),
        "webpage_url": _as_str(data.get("webpage_url")),
        "original_url": _as_str(data.get("original_url")),
        "display_id": _as_str(data.get("display_id")),
    }

    entries = data.get("entries")
    entry_items = _as_dict_list(entries)
    is_playlist = isinstance(entries, list)
    playlist_entries = [
        _playlist_entry(index, item)
        for index, item in enumerate(entry_items, start=1)
    ]

    collection_title: str | None = None
    collection_cover: str | None = None
    collection_entries: list[PlaylistEntry] = []
    if _is_bilibili_url(request.url):
        collection_title, collection_entries, collection_cover = _bilibili_collection_entries(request.url, cookie_file=cookie_file)
        if collection_entries:
            playlist_entries = collection_entries
            is_playlist = True
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
        raw["warning_code"] = "metadata_without_formats"
        raw["warning"] = "metadata_without_formats"
        formats = [
            FormatInfo(format_id="best", ext=_as_str(data.get("ext")), resolution=_as_str(data.get("resolution")) or "best", type="video+audio"),
            FormatInfo(format_id="bestaudio", ext=None, resolution=None, type="audio"),
        ]

    subtitles: list[SubtitleInfo] = []
    for automatic, source in ((False, _string_map(data.get("subtitles"))), (True, _string_map(data.get("automatic_captions")))):
        for language, entries in source.items():
            subtitles.append(
                SubtitleInfo(
                    language=str(language),
                    name=str(language),
                    automatic=automatic,
                    formats=sorted({str(entry.get("ext")) for entry in _as_dict_list(entries) if entry.get("ext")}),
                )
            )

    thumbnail_url = collection_cover or _best_thumbnail(data)
    if not thumbnail_url and is_playlist:
        for item in entry_items:
            thumbnail_url = _best_thumbnail(item)
            if thumbnail_url:
                raw["thumbnail_source"] = "first_playlist_entry"
                break

    return AnalyzeResponse(
        url=request.url,
        title=collection_title or _as_str(data.get("title")),
        channel=_as_str(data.get("channel") or data.get("uploader")),
        duration=_as_float(data.get("duration")),
        thumbnail_url=thumbnail_url,
        is_playlist=is_playlist,
        playlist_count=len(playlist_entries) if is_playlist else None,
        playlist_entries=playlist_entries,
        formats=formats,
        subtitles=subtitles,
        raw=raw,
    )
