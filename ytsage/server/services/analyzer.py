"""Generic yt-dlp analysis orchestration."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import requests
from fastapi import HTTPException, status

from ..analyzers import bilibili
from ..models import AnalyzeRequest, AnalyzeResponse, FormatInfo, PlaylistEntry, SubtitleInfo
from ..providers.base import ProviderError
from ..providers.bilibili import BilibiliProviderError
from ..providers.douyin import canonical_douyin_video_url, canonicalize_douyin_video_url
from .cookies import COOKIE_PROFILES, cookie_file_for_url, cookie_file_path, cookie_profile_for_url, cookie_profile_status, save_cookie_login_status, youtube_login_cookies_present
from .dependencies import ytdlp_base_command
from .douyin_proofs import DouyinDownloadProofStore

if TYPE_CHECKING:
    from .accounts import AccountService


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


def _has_downloadable_formats(items: Any) -> bool:
    for item in _as_dict_list(items):
        media_url = _as_str(item.get("url") or item.get("manifest_url"))
        if item.get("format_id") and media_url and urlparse(media_url).scheme in {"http", "https"}:
            return True
    return False


def _safe_media_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        return None
    return value


def _douyin_download_info(data: dict[str, Any], canonical_url: str) -> dict[str, object] | None:
    formats: list[dict[str, object]] = []
    for item in _as_dict_list(data.get("formats")):
        media_url = _safe_media_url(item.get("url"))
        format_id = _as_str(item.get("format_id"))
        if not media_url or not format_id:
            continue
        media_format: dict[str, object] = {
            "format_id": format_id,
            "url": media_url,
            "http_headers": {"Referer": canonical_url},
        }
        for key in ("ext", "vcodec", "acodec"):
            value = _as_str(item.get(key))
            if value:
                media_format[key] = value
        for key in ("width", "height", "filesize", "filesize_approx"):
            value = _as_int(item.get(key))
            if value is not None:
                media_format[key] = value
        for key in ("fps", "tbr"):
            value = _as_float(item.get(key))
            if value is not None:
                media_format[key] = value
        formats.append(media_format)
    if not formats:
        return None
    media_id = canonical_url.rstrip("/").rsplit("/", 1)[-1]
    result: dict[str, object] = {
        "id": media_id,
        "title": _as_str(data.get("title")) or "Douyin video",
        "webpage_url": canonical_url,
        "extractor": "DouyinBrowser",
        "formats": formats,
    }
    for key in ("channel", "uploader", "thumbnail"):
        value = _as_str(data.get(key))
        if value:
            result[key] = value
    duration = _as_float(data.get("duration"))
    if duration is not None:
        result["duration"] = duration
    return result


def _douyin_browser_failure(exc: ProviderError) -> HTTPException:
    if exc.code == "account_login_invalid":
        return HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail={"code": "fresh_cookies_required", "message": "Fresh Douyin cookies are required."},
        )
    code = exc.code if exc.code in {"provider_risk_control", "provider_timeout", "provider_unavailable"} else "provider_unavailable"
    http_status = exc.status_code if code != "provider_unavailable" else status.HTTP_503_SERVICE_UNAVAILABLE
    message = {
        "provider_risk_control": "Douyin blocked the analysis with a verification challenge.",
        "provider_timeout": "Douyin analysis timed out. Try again.",
        "provider_unavailable": "Douyin analysis is currently unavailable.",
    }[code]
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


def _douyin_analysis_failure(output: str, *, timed_out: bool = False) -> HTTPException:
    text = output.lower()
    if timed_out:
        code, message, http_status = "provider_timeout", "Douyin analysis timed out. Try again.", status.HTTP_504_GATEWAY_TIMEOUT
    elif "403" in text or any(marker in text for marker in ("captcha", "challenge", "risk control", "risk-control", "verify you are human")):
        code, message, http_status = "provider_risk_control", "Douyin blocked the analysis with a verification challenge.", status.HTTP_503_SERVICE_UNAVAILABLE
    elif any(marker in text for marker in ("fresh cookies", "cookies are no longer valid", "login required", "sign in to confirm", "not logged in")):
        code, message, http_status = "fresh_cookies_required", "Fresh Douyin cookies are required.", status.HTTP_424_FAILED_DEPENDENCY
    else:
        code, message, http_status = "provider_unavailable", "Douyin analysis is currently unavailable.", status.HTTP_503_SERVICE_UNAVAILABLE
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


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
    title = _as_str(item.get("title"))
    attr = int(_as_float(item.get("attr")) or 0)
    unavailable = bool(attr & 1) or (title or "").strip(" []【】") == "已失效视频"
    entry_url = None if unavailable else _entry_url_from_item(item)
    return PlaylistEntry(
        index=index,
        id=_as_str(item.get("id")) or _as_str(item.get("url")),
        title=title,
        url=entry_url,
        webpage_url=entry_url,
        duration=_as_float(item.get("duration")),
        channel=_as_str(item.get("channel") or item.get("uploader")),
        thumbnail_url=_best_thumbnail(item),
        is_available=not unavailable,
        unavailable_reason="Video is no longer available." if unavailable else None,
    )


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


def analyze(
    request: AnalyzeRequest,
    timeout: int = 60,
    config_dir: Path | None = None,
    account_service: AccountService | None = None,
    douyin_proofs: DouyinDownloadProofStore | None = None,
) -> AnalyzeResponse:
    cookie_file = None
    selected_account = None
    if request.account_id:
        if account_service is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Account selection is unavailable.")
        try:
            selected_account = account_service.storage.get_account(request.account_id)
            expected_profile = cookie_profile_for_url(request.url)
            if expected_profile != selected_account.platform:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The selected account does not match this URL.")
            cookie_file = account_service.resolve_cookie_file(request.account_id, expected_profile)
        except KeyError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_424_FAILED_DEPENDENCY, detail=str(exc)) from exc
    elif config_dir is not None:
        cookie_file = cookie_file_for_url(config_dir, request.url)
    requested_profile = cookie_profile_for_url(request.url)
    requested_cookie_status = cookie_profile_status(cookie_file_path(config_dir, requested_profile)) if config_dir is not None else None
    favorite_resource_id = bilibili.favorite_resource_id(request.url)
    account_favorite = None
    if favorite_resource_id and selected_account is not None and account_service is not None:
        try:
            account_favorite = account_service.list_all_entries(selected_account.id, favorite_resource_id)
        except BilibiliProviderError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    douyin_account_video = None
    direct_douyin_url = canonicalize_douyin_video_url(request.url) if requested_profile == "douyin" else None
    if direct_douyin_url and selected_account is not None and account_service is not None:
        try:
            douyin_account_video = account_service.douyin_video_info(selected_account.id, direct_douyin_url)
        except ProviderError as exc:
            raise _douyin_browser_failure(exc) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_424_FAILED_DEPENDENCY, detail=str(exc)) from exc

    if account_favorite is not None:
        # The account provider is authoritative for favorites and also handles empty collections.
        data: dict[str, Any] = {}
    elif douyin_account_video is not None:
        data = douyin_account_video
    else:
        cmd = [*ytdlp_base_command(), "--dump-single-json", "--flat-playlist", "--skip-download"]
        if cookie_file is not None:
            cmd.extend(["--cookies", str(cookie_file)])
        if request.generic_mode:
            cmd.append("--ignore-no-formats-error")
        cmd.append(request.url)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
        except FileNotFoundError as exc:
            if requested_profile == "douyin":
                raise _douyin_analysis_failure("") from exc
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="yt-dlp is not installed") from exc
        except subprocess.TimeoutExpired as exc:
            if requested_profile == "douyin":
                raise _douyin_analysis_failure("", timed_out=True) from exc
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="URL analysis timed out") from exc
        if result.returncode != 0:
            if requested_profile == "douyin":
                raise _douyin_analysis_failure(f"{result.stderr}\n{result.stdout}")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result.stderr.strip() or result.stdout.strip() or "yt-dlp analysis failed")
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            if requested_profile == "douyin":
                raise _douyin_analysis_failure("") from exc
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="yt-dlp returned invalid JSON") from exc

    raw: dict[str, Any] = {key: _as_str(data.get(key)) for key in ("extractor", "extractor_key", "webpage_url", "original_url", "display_id")}
    if selected_account is not None:
        actual_status = cookie_profile_status(cookie_file)
        raw["account_id"] = selected_account.id
        raw["account_label"] = selected_account.label
        raw["cookie_profile"] = selected_account.platform
        raw["cookie_expiry_status"] = actual_status.state
        raw["cookie_login_status"] = selected_account.state
        raw["account_identity_state"] = selected_account.state
        raw["target_extraction_state"] = "not_probed"
        raw["cookie_status"] = "account_verified" if selected_account.state == "valid" else "account_unverified"
    elif cookie_file is not None and config_dir is not None:
        actual_profile = next(
            (profile for profile in COOKIE_PROFILES if cookie_file_path(config_dir, profile) == cookie_file),
            requested_profile,
        )
        actual_status = cookie_profile_status(cookie_file)
        raw["cookie_profile"] = actual_profile
        raw["cookie_expiry_status"] = actual_status.state
        raw["cookie_status"] = "verified_for_url" if actual_profile == requested_profile else "fallback_verified"
        if actual_profile == "bilibili":
            raw["cookie_login_status"] = bilibili.validate_cookie_login(cookie_file, min(timeout, 10), requests)
        elif actual_profile == "youtube":
            rotated = "cookies are no longer valid" in result.stderr.lower()
            raw["cookie_login_status"] = "invalid" if rotated or not youtube_login_cookies_present(cookie_file) else "valid"
        else:
            raw["cookie_login_status"] = "unknown"
        save_cookie_login_status(config_dir, actual_profile, raw["cookie_login_status"])
    elif requested_cookie_status is not None and requested_cookie_status.configured:
        raw["cookie_profile"] = requested_profile
        raw["cookie_expiry_status"] = requested_cookie_status.state
        raw["cookie_login_status"] = "invalid" if requested_cookie_status.state in {"expired", "invalid"} else "unknown"
        raw["cookie_status"] = requested_cookie_status.state
    entries = data.get("entries")
    entry_items = _as_dict_list(entries)
    is_playlist = isinstance(entries, list)
    playlist_entries = [_playlist_entry(index, item) for index, item in enumerate(entry_items, start=1)]
    if requested_profile == "douyin":
        if is_playlist:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Douyin downloads currently support single videos only.",
            )
        resolved_video_url = canonical_douyin_video_url(data, request.url)
        if resolved_video_url is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="The Douyin URL did not resolve to a supported single video.",
            )
        raw["resolved_single_video_url"] = resolved_video_url

    collection_title = collection_cover = None
    if account_favorite is not None and selected_account is not None and account_service is not None:
        favorite_resource, favorite_entries = account_favorite
        playlist_entries = account_service.expand_playlist_entries(selected_account.id, favorite_entries)
        collection_title = favorite_resource.title
        collection_cover = favorite_resource.cover_url
        is_playlist = True
        raw["playlist_source"] = "bilibili_account_favorite"
        raw["collection_title"] = collection_title
        if collection_cover:
            raw["collection_cover"] = collection_cover
    elif _is_bilibili_url(request.url):
        collection_title, collection_entries, collection_cover = _bilibili_collection_entries(request.url, cookie_file)
        if collection_entries:
            playlist_entries, is_playlist = collection_entries, True
            raw["playlist_source"] = "bilibili_ugc_season"
            if collection_title:
                raw["collection_title"] = collection_title
            if collection_cover:
                raw["collection_cover"] = collection_cover

    formats = _formats_from(data.get("formats", []))
    douyin_has_downloadable_formats = requested_profile == "douyin" and _has_downloadable_formats(data.get("formats", []))
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
    if selected_account is not None and account_favorite is None:
        raw["target_extraction_state"] = "valid" if formats else "unavailable"
    if requested_profile == "douyin":
        raw["target_extraction_state"] = "valid" if douyin_has_downloadable_formats else "unavailable"
    if not formats or (requested_profile == "douyin" and not douyin_has_downloadable_formats):
        raw["warning_code"] = raw["warning"] = "metadata_without_formats"
        if not formats:
            formats = [FormatInfo(format_id="best", ext=_as_str(data.get("ext")), resolution=_as_str(data.get("resolution")) or "best", type="video+audio"), FormatInfo(format_id="bestaudio", type="audio")]

    thumbnail_url = collection_cover or _best_thumbnail(data)
    if not thumbnail_url and is_playlist:
        for item in entry_items:
            thumbnail_url = _best_thumbnail(item)
            if thumbnail_url:
                raw["thumbnail_source"] = "first_playlist_entry"
                break

    proof = None
    if requested_profile == "douyin" and douyin_has_downloadable_formats and douyin_proofs is not None:
        download_info = _douyin_download_info(data, raw["resolved_single_video_url"])
        if download_info is not None:
            proof = douyin_proofs.issue(
                raw["resolved_single_video_url"],
                request.account_id,
                download_info,
            )
    return AnalyzeResponse(url=request.url, title=collection_title or _as_str(data.get("title")), channel=_as_str(data.get("channel") or data.get("uploader")), duration=_as_float(data.get("duration")), thumbnail_url=thumbnail_url, is_playlist=is_playlist, playlist_count=len(playlist_entries) if is_playlist else None, playlist_entries=playlist_entries, formats=formats, subtitles=_subtitles_from(data), raw=raw, douyin_download_proof=proof)
