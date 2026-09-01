from __future__ import annotations

import http.cookiejar
import json
import re
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import requests

from ..models import PlaylistEntry


class HttpClient(Protocol):
    def get(self, url: str, **kwargs: Any) -> requests.Response: ...


def as_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_int(value: Any) -> int | None:
    number = as_float(value)
    return int(number) if number is not None else None


def as_dict_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def is_bilibili_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host.endswith("bilibili.com") or host.endswith("b23.tv")


def _space_list_params(url: str) -> tuple[str, str] | None:
    match = re.search(r"space\.bilibili\.com/(\d+)/lists/(\d+)", url)
    return (match.group(1), match.group(2)) if match else None


def _json_response(response: requests.Response) -> dict[str, Any] | None:
    try:
        return json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
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


def _space_collection_entries(url: str, cookie_file: Path | None, timeout: int, http: HttpClient) -> tuple[str | None, list[PlaylistEntry], str | None]:
    params = _space_list_params(url)
    if not params:
        return None, [], None
    mid, season_id = params
    entries: list[PlaylistEntry] = []
    collection_title = collection_cover = None
    page_num, page_size = 1, 100
    while True:
        try:
            response = http.get(
                "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list",
                params={"mid": mid, "season_id": season_id, "page_num": page_num, "page_size": page_size},
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36", "Referer": url},
                cookies=_load_cookie_jar(cookie_file),
                timeout=timeout,
            )
        except requests.RequestException:
            break
        if response.status_code >= 400:
            break
        payload = _json_response(response)
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            break
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        collection_title = collection_title or as_str(meta.get("title")) or as_str(meta.get("name"))
        collection_cover = collection_cover or as_str(meta.get("cover"))
        archives = as_dict_list(data.get("archives"))
        for archive in archives:
            bvid, aid = as_str(archive.get("bvid")), as_str(archive.get("aid"))
            entry_url = f"https://www.bilibili.com/video/{bvid}" if bvid else None
            entries.append(PlaylistEntry(index=len(entries) + 1, id=bvid or aid, title=as_str(archive.get("title")), url=entry_url, webpage_url=entry_url, duration=as_float(archive.get("duration")), thumbnail_url=as_str(archive.get("pic"))))
        page = data.get("page") if isinstance(data.get("page"), dict) else {}
        total = as_int(page.get("total")) or len(entries)
        if len(entries) >= total or not archives:
            break
        page_num += 1
        if page_num > 20:
            break
    return collection_title, entries, collection_cover


def _bvid_from_url(url: str) -> str | None:
    match = re.search(r"/(BV[0-9A-Za-z]+)/?", url)
    return match.group(1) if match else None


def _extract_balanced_json(text: str, marker: str) -> dict[str, Any] | None:
    start = text.find(marker)
    if start < 0:
        return None
    start = text.find("{", start)
    if start < 0:
        return None
    depth, in_string, escape = 0, False, False
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


def _episode_title(episode: dict[str, Any]) -> str | None:
    arc = episode.get("arc") if isinstance(episode.get("arc"), dict) else {}
    title = as_str(episode.get("title")) or as_str(episode.get("long_title")) or as_str(episode.get("part")) or as_str(arc.get("title"))
    return title or (f"P{as_int(episode.get('page'))}" if as_int(episode.get("page")) else None)


def _pages_entries(data: dict[str, Any], bvid: str) -> list[PlaylistEntry]:
    entries: list[PlaylistEntry] = []
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    channel, default_cover = as_str(owner.get("name")), as_str(data.get("pic"))
    for position, page_data in enumerate(as_dict_list(data.get("pages")), start=1):
        page = as_int(page_data.get("page")) or position
        entry_url = f"https://www.bilibili.com/video/{bvid}/?p={page}"
        entries.append(PlaylistEntry(index=position, id=f"{bvid}_p{page}", title=as_str(page_data.get("part")) or f"P{page}", url=entry_url, webpage_url=entry_url, duration=as_float(page_data.get("duration")), channel=channel, thumbnail_url=as_str(page_data.get("first_frame")) or default_cover))
    return entries


def entries_from_season(season: Any) -> tuple[str | None, list[PlaylistEntry]]:
    if not isinstance(season, dict):
        return None, []
    collection_title = as_str(season.get("title"))
    entries: list[PlaylistEntry] = []
    for section in as_dict_list(season.get("sections")):
        for episode in as_dict_list(section.get("episodes")):
            bvid = as_str(episode.get("bvid")) or as_str(episode.get("bvid_str"))
            aid, page = as_str(episode.get("aid")), as_int(episode.get("page"))
            entry_url = f"https://www.bilibili.com/video/{bvid}/" if bvid else None
            if entry_url and page and page > 1:
                entry_url = f"{entry_url}?p={page}"
            arc = episode.get("arc") if isinstance(episode.get("arc"), dict) else {}
            entries.append(PlaylistEntry(index=len(entries) + 1, id=bvid or aid, title=_episode_title(episode), url=entry_url, webpage_url=entry_url, duration=as_float(episode.get("duration")) or as_float(arc.get("duration")), thumbnail_url=as_str(episode.get("cover")) or as_str(arc.get("pic"))))
    return collection_title, entries


def collection_from_api(url: str, cookie_file: Path | None = None, timeout: int = 15, http: HttpClient = requests) -> tuple[str | None, list[PlaylistEntry]]:
    bvid = _bvid_from_url(url)
    if not bvid:
        return None, []
    try:
        response = http.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid}, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36", "Referer": url}, cookies=_load_cookie_jar(cookie_file), timeout=timeout)
    except requests.RequestException:
        return None, []
    if response.status_code >= 400:
        return None, []
    payload = _json_response(response)
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return None, []
    title, entries = entries_from_season(data.get("ugc_season"))
    if entries:
        return title, entries
    page_entries = _pages_entries(data, bvid)
    return (as_str(data.get("title")), page_entries) if len(page_entries) > 1 else (None, [])


def collection_entries(url: str, cookie_file: Path | None = None, timeout: int = 15, http: HttpClient = requests) -> tuple[str | None, list[PlaylistEntry], str | None]:
    title, entries, cover = _space_collection_entries(url, cookie_file, timeout, http)
    if entries:
        return title, entries, cover
    if not is_bilibili_url(url):
        return None, [], None
    try:
        response = http.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36", "Referer": "https://www.bilibili.com/"}, cookies=_load_cookie_jar(cookie_file), timeout=timeout)
    except requests.RequestException:
        return None, [], None
    if response.status_code >= 400:
        return None, [], None
    state = _extract_balanced_json(response.text, "window.__INITIAL_STATE__=")
    if not state:
        return (*collection_from_api(url, cookie_file, timeout, http), None)
    title, entries = entries_from_season(state.get("ugc_season") or state.get("ugcSeason"))
    return (title, entries, None) if entries else (*collection_from_api(url, cookie_file, timeout, http), None)
