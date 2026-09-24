"""Douyin account identity verification for imported web cookies."""

from __future__ import annotations

from http.cookiejar import MozillaCookieJar
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse

import requests

from .base import PlatformIdentity, ProviderError

_ACCOUNT_INFO_URL = "https://www.douyin.com/aweme/v1/web/user/profile/self/"
_ACCOUNT_INFO_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "pc_client_type": "1",
    "version_code": "190500",
    "version_name": "19.5.0",
    "cookie_enabled": "true",
    "platform": "PC",
    "downlink": "10",
}
_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.douyin.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36",
}
_LOGIN_COOKIE_NAMES = {"sessionid", "sessionid_ss", "sid_tt", "sid_tt_ss", "sid_guard"}
_DOUYIN_COOKIE_DOMAINS = ("douyin.com", "iesdouyin.com")
_DOUYIN_VIDEO_PATH = re.compile(r"^/(?:video|share/video)/(\d+)/?$")
_RISK_HTTP_STATUSES = {403, 461, 471}
_RISK_CODES = {461, 471, 2156, 4031}
_RISK_MARKERS = (
    "风控", "验证码", "人机验证", "安全风险", "captcha", "risk",
    "verification required", "verify required", "please verify",
)
_INVALID_LOGIN_MARKERS = ("未登录", "登录失效", "登录过期", "login expired", "not logged in", "not login")
_AVATAR_HOST_SUFFIXES = (
    ".douyinpic.com",
    ".douyincdn.com",
    ".byteimg.com",
    ".pstatp.com",
    ".douyinstatic.com",
)


class DouyinProviderError(ProviderError):
    pass


def _host_matches_domain(host: str, domain: str) -> bool:
    normalized = domain.lstrip(".").lower()
    return host == normalized or host.endswith(f".{normalized}")


def is_douyin_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(_host_matches_domain(host, domain) for domain in _DOUYIN_COOKIE_DOMAINS)


def canonicalize_douyin_video_url(url: str) -> str | None:
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    match = _DOUYIN_VIDEO_PATH.fullmatch(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not is_douyin_url(url)
        or host == "v.douyin.com"
        or match is None
    ):
        return None
    return f"https://www.douyin.com/video/{match.group(1)}"


def is_douyin_single_video_url(url: str) -> bool:
    return canonicalize_douyin_video_url(url) is not None


def canonical_douyin_video_url(data: dict[str, Any], request_url: str) -> str | None:
    for value in (data.get("webpage_url"), data.get("original_url"), request_url):
        if isinstance(value, str):
            canonical = canonicalize_douyin_video_url(value)
            if canonical is not None:
                return canonical
    media_id = data.get("id")
    extractor = str(data.get("extractor_key") or data.get("extractor") or "").lower()
    if media_id is not None and str(media_id).isdigit() and "douyin" in extractor:
        return f"https://www.douyin.com/video/{media_id}"
    return None


class DouyinProvider:
    platform = "douyin"
    cookie_domain = ".douyin.com"
    # A blocked identity endpoint does not prove that yt-dlp cannot use the cookie.
    allow_unverified_import = True

    def __init__(self, timeout: int = 15, http: Any = requests, resource_client: Any | None = None) -> None:
        self.timeout = timeout
        self.http = http
        if resource_client is None:
            from .douyin_browser import DouyinResourceClient
            resource_client = DouyinResourceClient()
        self.resource_client = resource_client

    def list_resources(self, account: Any, cookie_file: Path, kind: str, offset: int, limit: int) -> Any:
        return self.resource_client.list_resources(account, cookie_file, kind, offset, limit)

    def list_entries(self, account: Any, cookie_file: Path, resource_id: str, offset: int, limit: int) -> Any:
        return self.resource_client.list_entries(account, cookie_file, resource_id, offset, limit)

    def close(self) -> None:
        self.resource_client.close()

    def warm(self, account: Any, cookie_file: Path) -> None:
        self.resource_client.warm(account, cookie_file)

    def browser_capability(self) -> dict[str, Any]:
        return self.resource_client.capability()

    def validate_cookie_file(self, cookie_file: Path) -> None:
        login_cookies = [
            cookie for cookie in _load_cookie_jar(cookie_file)
            if cookie.name.lower() in _LOGIN_COOKIE_NAMES
            and any(_host_matches_domain(cookie.domain.lower().lstrip("."), domain) for domain in _DOUYIN_COOKIE_DOMAINS)
        ]
        if not login_cookies:
            raise DouyinProviderError(
                "account_login_invalid",
                "The Douyin cookies do not contain a signed-in web session. Import the complete cookies from a logged-in browser.",
                424,
            )

    def verify(self, cookie_file: Path) -> PlatformIdentity:
        self.validate_cookie_file(cookie_file)
        try:
            response = self.http.get(
                _ACCOUNT_INFO_URL,
                params=_ACCOUNT_INFO_PARAMS,
                headers=_HEADERS,
                cookies=_load_cookie_jar(cookie_file),
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DouyinProviderError(
                "provider_unavailable",
                "Douyin identity verification is currently unavailable.",
                503,
            ) from exc

        if response.status_code in _RISK_HTTP_STATUSES or response.status_code == 429:
            raise DouyinProviderError(
                "provider_risk_control",
                "Douyin blocked the identity check. The cookies were saved, but their login state could not be confirmed.",
                503,
            )
        if response.status_code >= 500 or response.status_code in {404, 405, 410}:
            raise DouyinProviderError("provider_unavailable", "Douyin identity verification is currently unavailable.", 503)
        if response.status_code < 200 or response.status_code >= 300:
            raise DouyinProviderError(
                "provider_response_invalid",
                f"Douyin identity verification returned HTTP {response.status_code}.",
            )

        text = response.text.strip()
        if _looks_like_html(text):
            raise DouyinProviderError(
                "provider_risk_control",
                "Douyin returned a risk-control page instead of account identity data.",
                503,
            )
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise DouyinProviderError("provider_response_invalid", "Douyin returned invalid account identity data.") from exc
        if not isinstance(payload, dict):
            raise DouyinProviderError("provider_response_invalid", "Douyin returned invalid account identity data.")

        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        user = payload.get("user") if isinstance(payload.get("user"), dict) else None
        if user is None:
            user = data.get("user") if isinstance(data.get("user"), dict) else data
        code = _as_int(
            payload.get("status_code"), payload.get("error_code"), payload.get("code"),
            data.get("status_code"), data.get("error_code"), data.get("code"),
        )
        message = _first_text(
            data.get("description"), payload.get("status_msg"), data.get("message"), payload.get("message"),
        ) or ""
        if code in _RISK_CODES or any(marker in message.lower() for marker in _RISK_MARKERS):
            raise DouyinProviderError(
                "provider_risk_control",
                "Douyin blocked the identity check. The cookies were saved, but their login state could not be confirmed.",
                503,
            )
        if (
            code == 1041
            or data.get("has_login") is False
            or payload.get("has_login") is False
            or any(marker in message.lower() for marker in _INVALID_LOGIN_MARKERS)
        ):
            raise DouyinProviderError("account_login_invalid", "The Douyin login is no longer valid.", 424)
        if code not in {None, 0}:
            raise DouyinProviderError("provider_response_invalid", "Douyin returned an account identity error.")

        external_id = _first_text(
            user.get("user_id_str"), user.get("uid_str"), user.get("user_id"), user.get("uid"), user.get("sec_uid"),
            data.get("user_id_str"), data.get("uid_str"), data.get("user_id"), data.get("uid"), data.get("sec_uid"),
        )
        if not external_id or external_id == "0":
            raise DouyinProviderError("provider_response_invalid", "Douyin did not return a stable account identity.")
        display_name = _first_text(
            user.get("screen_name"), user.get("nickname"), user.get("name"), user.get("unique_id"),
        ) or external_id
        avatar_url = _avatar_url(user) or _avatar_url(data)
        return PlatformIdentity(external_id, display_name, avatar_url)


def _load_cookie_jar(path: Path) -> MozillaCookieJar:
    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, ValueError) as exc:
        raise DouyinProviderError("account_login_invalid", "The Douyin cookie file is invalid.", 424) from exc
    return jar


def _looks_like_html(value: str) -> bool:
    lowered = value.lower()
    return lowered.startswith("<!doctype html") or lowered.startswith("<html") or "<script" in lowered


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None or isinstance(value, (dict, list, bool)):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _as_int(*values: Any) -> int | None:
    for value in values:
        if value is None or isinstance(value, bool):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _safe_avatar_url(value: str) -> str | None:
    url = f"https:{value}" if value.startswith("//") else value
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not any(host.endswith(suffix) for suffix in _AVATAR_HOST_SUFFIXES)
    ):
        return None
    return url


def _avatar_url(data: dict[str, Any]) -> str | None:
    direct = _first_text(data.get("avatar_url"), data.get("avatar"))
    if direct:
        safe = _safe_avatar_url(direct)
        if safe:
            return safe
    for key in ("avatar_thumb", "avatar_medium", "avatar_larger"):
        value = data.get(key)
        if not isinstance(value, dict):
            continue
        urls = value.get("url_list")
        if isinstance(urls, list):
            for url in urls:
                if isinstance(url, str):
                    safe = _safe_avatar_url(url)
                    if safe:
                        return safe
    return None
