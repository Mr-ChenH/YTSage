"""Playwright-backed, first-party Douyin library browsing.

The adapter navigates genuine www.douyin.com pages and observes only the site's
read-only JSON response families for works, favorites, collection folders, and
folder entries. It never constructs signed API requests or exposes cursors.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..models import AccountResource, AccountResourceEntriesResponse, AccountResourceListResponse, PageInfo, PlatformAccount, PlaylistEntry
from .base import ProviderError
from .douyin import canonicalize_douyin_video_url

_RESPONSE_FAMILIES = {
    "douyin_works": ("/aweme/v1/web/aweme/post/",),
    "douyin_favorites": ("/aweme/v1/web/aweme/listcollection/",),
    "douyin_collections": ("/aweme/v1/web/collects/list/",),
    "douyin_collection": ("/aweme/v1/web/collects/video/list/",),
    "douyin_video": ("/aweme/v1/web/aweme/detail/",),
}
_MAX_SCROLLS = 40
_PROFILE_URL = "https://www.douyin.com/user/self"
_PAGE_URLS = {
    "douyin_works": _PROFILE_URL,
    "douyin_favorites": _PROFILE_URL,
    "douyin_collections": _PROFILE_URL,
}
_IMAGE_SUFFIXES = (".douyinpic.com", ".douyincdn.com", ".byteimg.com", ".pstatp.com", ".douyinstatic.com")
_MEDIA_SUFFIXES = (".douyinvod.com", ".douyinstatic.com", ".douyincdn.com", ".byteimg.com", ".pstatp.com")
_COLLECTION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_RISK_CODES = {461, 471, 2156, 4031}
_RISK_MARKERS = (
    "风控", "验证码", "人机验证", "安全风险", "captcha", "risk",
    "verification required", "verify required", "please verify",
)
_LOGIN_MARKERS = ("未登录", "登录失效", "登录过期", "login expired", "not logged in", "not login")
_TIMEOUT_HTTP_STATUSES = {408, 504, 522, 524, 598, 599}
_CAPABILITY_LOCK = threading.Lock()
_CAPABILITY_CACHE: dict[str, Any] | None = None
_RESOURCE_CACHE_FRESH_SECONDS = 300.0
_RESOURCE_CACHE_MAX_ENTRIES = 128
_IMAGE_TOKEN_TTL_SECONDS = 600.0
_IMAGE_TOKEN_MAX_ENTRIES = 256


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    result = str(value).strip()
    return result or None


def _integer(value: Any) -> int | None:
    try:
        return None if value is None or isinstance(value, bool) else int(value)
    except (TypeError, ValueError):
        return None


def _image(value: Any) -> str | None:
    return _image_url(value, keep_query=False)


def _signed_image(value: Any) -> str | None:
    return _image_url(value, keep_query=True)


def _image_url(value: Any, *, keep_query: bool) -> str | None:
    values = value.get("url_list") if isinstance(value, dict) else [value]
    for candidate in values if isinstance(values, list) else []:
        if not isinstance(candidate, str):
            continue
        url = f"https:{candidate}" if candidate.startswith("//") else candidate
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        try:
            port = parsed.port
        except ValueError:
            continue
        if parsed.scheme == "https" and parsed.username is None and parsed.password is None and port in {None, 443} and any(host.endswith(s) for s in _IMAGE_SUFFIXES):
            return parsed._replace(query=parsed.query if keep_query else "", fragment="").geturl()
    return None


@dataclass(frozen=True)
class BrowserCapture:
    payloads: list[dict[str, Any]]
    truncated: bool = False


def clear_chromium_capability_cache() -> None:
    global _CAPABILITY_CACHE
    with _CAPABILITY_LOCK:
        _CAPABILITY_CACHE = None


def chromium_capability() -> dict[str, Any]:
    """Verify that the installed Chromium binary can actually launch."""
    global _CAPABILITY_CACHE
    with _CAPABILITY_LOCK:
        if _CAPABILITY_CACHE is not None:
            return dict(_CAPABILITY_CACHE)
        runtime = None
        browser = None
        available = False
        try:
            from playwright.sync_api import sync_playwright
            runtime = sync_playwright().start()
            executable = Path(runtime.chromium.executable_path)
            if executable.is_file() and os.access(executable, os.X_OK):
                browser = runtime.chromium.launch(channel="chromium", headless=True)
                available = True
        except Exception:
            available = False
        finally:
            if browser is not None:
                try:
                    browser.close()
                except Exception:
                    available = False
            if runtime is not None:
                try:
                    runtime.stop()
                except Exception:
                    available = False
        _CAPABILITY_CACHE = {"available": available, "engine": "playwright-chromium"}
        return dict(_CAPABILITY_CACHE)


def _capture_page(
    page: Any,
    page_url: str,
    families: tuple[str, ...],
    *,
    target_count: int,
    payload_kind: str,
    resource_kind: str,
    timeout_ms: int,
    reuse_profile: bool,
    seed_payloads: list[dict[str, Any]] | None = None,
    continue_current: bool = False,
) -> BrowserCapture:
    payloads: list[dict[str, Any]] = list(seed_payloads or [])
    response_errors: list[ProviderError] = []

    def receive(response: Any) -> None:
        parsed = urlparse(response.url)
        host = (parsed.hostname or "").lower()
        try:
            port = parsed.port
        except ValueError:
            return
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or not (host == "douyin.com" or host.endswith(".douyin.com"))
            or response.request.resource_type not in {"xhr", "fetch"}
            or not any(family in parsed.path for family in families)
        ):
            return
        http_error = _http_response_error(_integer(getattr(response, "status", None)))
        if http_error is not None:
            response_errors.append(http_error)
            return
        try:
            body = response.json()
        except Exception:
            response_errors.append(ProviderError("provider_response_invalid", "Douyin returned invalid library data.", 502))
            return
        if not isinstance(body, dict):
            response_errors.append(ProviderError("provider_response_invalid", "Douyin returned invalid library data.", 502))
            return
        payload_error = _payload_error(body)
        if payload_error is not None:
            response_errors.append(payload_error)
            return
        payloads.append(body)

    def raise_response_error() -> None:
        if response_errors:
            raise response_errors[0]

    page.on("response", receive)
    try:
        current_path = urlparse(getattr(page, "url", "")).path
        requested_path = urlparse(page_url).path
        can_reuse = reuse_profile and resource_kind in {"douyin_works", "douyin_favorites", "douyin_collections"} and current_path == requested_path
        if not continue_current and not can_reuse:
            page.goto(page_url, wait_until="domcontentloaded", timeout=timeout_ms)
        raise_response_error()
        _raise_for_page_state(page)
        if not continue_current:
            _dismiss_save_login_dialog(page)
            _navigate_library(page, resource_kind, refresh_works=can_reuse)
        raise_response_error()
        if not continue_current:
            for _ in range(max(1, timeout_ms // 200)):
                if payloads or response_errors:
                    break
                _raise_for_page_state(page)
                page.wait_for_timeout(200)
        raise_response_error()
        _raise_for_page_state(page)
        truncated = False
        for scroll_index in range(_MAX_SCROLLS + 1):
            raise_response_error()
            records = _payload_records(payloads, payload_kind)
            has_more = any(bool(payload.get("has_more")) for payload in payloads[-2:])
            if len(records) >= target_count:
                truncated = has_more
                break
            if payloads and not has_more:
                break
            if scroll_index == _MAX_SCROLLS:
                truncated = has_more
                break
            before = len(payloads)
            page.mouse.wheel(0, 2400)
            for _ in range(20):
                if len(payloads) > before or response_errors:
                    break
                page.wait_for_timeout(100)
            raise_response_error()
            if len(payloads) == before:
                truncated = has_more
                break
        _raise_for_page_state(page)
    finally:
        remove_listener = getattr(page, "remove_listener", None)
        if remove_listener:
            remove_listener("response", receive)
    if not payloads:
        raise ProviderError("provider_response_invalid", "Douyin did not return library data.", 502)
    return BrowserCapture(payloads, truncated)


class _AccountBrowserWorker:
    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="douyin-browser")
        self.runtime: Any | None = None
        self.browser: Any | None = None
        self.context: Any | None = None
        self.page: Any | None = None
        self.cookie_fingerprint: tuple[int, int] | None = None
        self.history: dict[tuple[str, str, str], BrowserCapture] = {}
        self.current_key: tuple[str, str, str] | None = None

    def observe(self, cookie_file: Path, page_url: str, families: tuple[str, ...], *, force_refresh: bool = False, **kwargs: Any) -> BrowserCapture:
        return self.executor.submit(self._observe, cookie_file, page_url, families, force_refresh, kwargs).result()

    def close(self) -> None:
        self.executor.submit(self._reset).result()
        self.executor.shutdown(wait=True)

    def _observe(self, cookie_file: Path, page_url: str, families: tuple[str, ...], force_refresh: bool, kwargs: dict[str, Any]) -> BrowserCapture:
        try:
            stat = cookie_file.stat()
            fingerprint = (stat.st_mtime_ns, stat.st_size)
            if self.cookie_fingerprint != fingerprint:
                self._reset()
            self._ensure_session(cookie_file, fingerprint)
            resource_kind = str(kwargs["resource_kind"])
            payload_kind = str(kwargs["payload_kind"])
            target_count = int(kwargs["target_count"])
            key = (resource_kind, page_url, payload_kind)
            previous = None if force_refresh else self.history.get(key)
            if previous is not None:
                records = _payload_records(previous.payloads, payload_kind)
                has_more = any(bool(payload.get("has_more")) for payload in previous.payloads[-2:])
                if len(records) >= target_count or not has_more:
                    return BrowserCapture(previous.payloads, has_more and len(records) >= target_count)
            capture = _capture_page(
                self.page,
                page_url,
                families,
                timeout_ms=self.timeout_ms,
                reuse_profile=True,
                seed_payloads=previous.payloads if previous is not None else None,
                continue_current=previous is not None and self.current_key == key,
                **kwargs,
            )
            self.history[key] = capture
            self.current_key = key
            return capture
        except Exception:
            self._reset()
            raise

    def _ensure_session(self, cookie_file: Path, fingerprint: tuple[int, int]) -> None:
        if self.page is not None:
            return
        from playwright.sync_api import sync_playwright

        self.runtime = sync_playwright().start()
        self.browser = self.runtime.chromium.launch(channel="chromium", headless=True)
        self.context = self.browser.new_context()
        self.context.add_cookies(_playwright_cookies(cookie_file))
        self.page = self.context.new_page()
        self.cookie_fingerprint = fingerprint

    def _reset(self) -> None:
        for value in (self.context, self.browser, self.runtime):
            if value is not None:
                try:
                    value.close() if hasattr(value, "close") else value.stop()
                except Exception:
                    pass
        self.page = None
        self.context = None
        self.browser = None
        self.runtime = None
        self.cookie_fingerprint = None
        self.history.clear()
        self.current_key = None


class PlaywrightDouyinDriver:
    """Account-isolated Playwright sessions with injectable ephemeral test support."""

    def __init__(self, timeout_ms: int = 20_000, playwright_factory: Any | None = None) -> None:
        self.timeout_ms = timeout_ms
        self.playwright_factory = playwright_factory
        self._workers: dict[str, _AccountBrowserWorker] = {}
        self._workers_lock = threading.Lock()

    def observe(
        self,
        cookie_file: Path,
        page_url: str,
        families: tuple[str, ...],
        *,
        target_count: int,
        payload_kind: str,
        resource_kind: str = "douyin_works",
        force_refresh: bool = False,
    ) -> BrowserCapture:
        try:
            from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout, sync_playwright
        except ImportError as exc:
            raise ProviderError("provider_unavailable", "Douyin browser support is not installed.", 503) from exc
        kwargs = {
            "target_count": target_count,
            "payload_kind": payload_kind,
            "resource_kind": resource_kind,
        }
        try:
            if self.playwright_factory is None:
                key = str(cookie_file.resolve())
                with self._workers_lock:
                    worker = self._workers.get(key)
                    if worker is None:
                        worker = _AccountBrowserWorker(self.timeout_ms)
                        self._workers[key] = worker
                return worker.observe(cookie_file, page_url, families, force_refresh=force_refresh, **kwargs)
            with self.playwright_factory() as runtime:
                browser = runtime.chromium.launch(channel="chromium", headless=True)
                context = None
                try:
                    context = browser.new_context()
                    context.add_cookies(_playwright_cookies(cookie_file))
                    page = context.new_page()
                    return _capture_page(
                        page,
                        page_url,
                        families,
                        timeout_ms=self.timeout_ms,
                        reuse_profile=False,
                        **kwargs,
                    )
                finally:
                    if context is not None:
                        context.close()
                    browser.close()
        except ProviderError:
            raise
        except PlaywrightTimeout as exc:
            raise ProviderError("provider_timeout", "Douyin browsing timed out.", 504) from exc
        except PlaywrightError as exc:
            raise ProviderError("provider_unavailable", "Douyin browser access is unavailable.", 503) from exc

    def close(self) -> None:
        with self._workers_lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.close()


def _http_response_error(status: int | None) -> ProviderError | None:
    if status is None or 200 <= status < 300:
        return None
    if status == 401:
        return ProviderError("account_login_invalid", "The Douyin login is no longer valid.", 424)
    if status in {403, 429, 461, 471}:
        return ProviderError("provider_risk_control", "Douyin requires interactive verification.", 503)
    if status in _TIMEOUT_HTTP_STATUSES:
        return ProviderError("provider_timeout", "Douyin browsing timed out.", 504)
    if status >= 500:
        return ProviderError("provider_unavailable", "Douyin browser access is unavailable.", 503)
    return ProviderError("provider_response_invalid", "Douyin returned invalid library data.", 502)


def _payload_error(payload: dict[str, Any]) -> ProviderError | None:
    code = _integer(payload.get("status_code"))
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    message = " ".join(filter(None, (
        _text(payload.get("status_msg")), _text(payload.get("message")),
        _text(data.get("description")), _text(data.get("message")),
    ))).lower()
    if code in _RISK_CODES or any(marker in message for marker in _RISK_MARKERS):
        return ProviderError("provider_risk_control", "Douyin requires interactive verification.", 503)
    if code == 1041 or payload.get("has_login") is False or data.get("has_login") is False or any(marker in message for marker in _LOGIN_MARKERS):
        return ProviderError("account_login_invalid", "The Douyin login is no longer valid.", 424)
    if code != 0:
        return ProviderError("provider_response_invalid", "Douyin returned invalid library data.", 502)
    return None


def _visible(locator: Any) -> bool:
    try:
        return bool(locator.is_visible())
    except Exception:
        return False


def _visible_matches(locator: Any) -> list[Any]:
    try:
        return [locator.nth(index) for index in range(locator.count()) if _visible(locator.nth(index))]
    except Exception:
        return []


def _raise_for_page_state(page: Any) -> None:
    url = str(page.url).lower()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if "/passport/" in path or "login" in path:
        raise ProviderError("account_login_invalid", "The Douyin login is no longer valid.", 424)
    if any(marker in host or marker in path for marker in ("captcha", "verifycenter", "/verify")):
        raise ProviderError("provider_risk_control", "Douyin requires interactive verification.", 503)
    for text in ("\u4eba\u673a\u9a8c\u8bc1", "\u5b89\u5168\u9a8c\u8bc1"):
        if _visible_matches(page.get_by_text(text, exact=True)):
            raise ProviderError("provider_risk_control", "Douyin requires interactive verification.", 503)
    challenge_nodes = page.locator('iframe[src*="captcha" i], iframe[src*="verifycenter" i], [id*="captcha" i], [class*="captcha" i]')
    if _visible_matches(challenge_nodes):
        raise ProviderError("provider_risk_control", "Douyin requires interactive verification.", 503)


def _click_node(node: Any) -> bool:
    try:
        node.click(timeout=1_000, force=True)
        return True
    except TypeError:
        node.click()
        return True
    except Exception:
        return False


def _dismiss_save_login_dialog(page: Any) -> bool:
    for dialog in _visible_matches(page.get_by_role("dialog")):
        if not _visible_matches(dialog.get_by_text("\u4fdd\u5b58\u767b\u5f55\u4fe1\u606f", exact=True)):
            continue
        for label in ("\u6682\u4e0d\u4fdd\u5b58", "\u4ee5\u540e\u518d\u8bf4", "\u53d6\u6d88"):
            buttons = _visible_matches(dialog.get_by_role("button", name=label, exact=True))
            if buttons and _click_node(buttons[0]):
                return True
        dialog.press("Escape")
        return True

    # Douyin's save-login prompt currently has no dialog role. Require its
    # exact title before clicking an exact dismiss label so unrelated controls
    # are never activated.
    if not _visible_matches(page.get_by_text("\u4fdd\u5b58\u767b\u5f55\u4fe1\u606f", exact=True)):
        return False
    for label in ("\u6682\u4e0d\u4fdd\u5b58", "\u4ee5\u540e\u518d\u8bf4", "\u53d6\u6d88"):
        buttons = _visible_matches(page.get_by_text(label, exact=True))
        if buttons and _click_node(buttons[0]):
            return True
    return False


def _click_visible_text(page: Any, text: str, *, attempts: int = 50) -> bool:
    for _ in range(attempts):
        matches = _visible_matches(page.get_by_text(text, exact=True))
        if matches and _click_node(matches[0]):
            page.wait_for_timeout(150)
            _raise_for_page_state(page)
            return True
        _raise_for_page_state(page)
        page.wait_for_timeout(200)
    return False


def _navigate_library(page: Any, resource_kind: str, *, refresh_works: bool = False) -> None:
    if resource_kind == "douyin_works":
        if refresh_works and not _click_visible_text(page, "\u4f5c\u54c1", attempts=25):
            raise ProviderError("provider_response_invalid", "Douyin works navigation is unavailable.", 502)
        return
    if resource_kind in {"douyin_collection", "douyin_video"}:
        return
    if resource_kind not in {"douyin_favorites", "douyin_collections"}:
        raise ProviderError("resource_not_found", "Unsupported Douyin library type.", 404)
    subtab = "\u89c6\u9891" if resource_kind == "douyin_favorites" else "\u6536\u85cf\u5939"
    for _ in range(3):
        if not _click_visible_text(page, "\u6536\u85cf"):
            continue
        for _ in range(100):
            _raise_for_page_state(page)
            if _dismiss_save_login_dialog(page):
                page.wait_for_timeout(400)
                break
            matches = _visible_matches(page.get_by_text(subtab, exact=True))
            if matches and _click_node(matches[0]):
                page.wait_for_timeout(150)
                _raise_for_page_state(page)
                return
            page.wait_for_timeout(100)
    raise ProviderError("provider_response_invalid", "Douyin library navigation is unavailable.", 502)


def _playwright_cookies(path: Path) -> list[dict[str, Any]]:
    jar = MozillaCookieJar(str(path))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except (OSError, ValueError) as exc:
        raise ProviderError("account_login_invalid", "The Douyin cookie file is invalid.", 424) from exc
    cookies = []
    for cookie in jar:
        if not (cookie.domain.lstrip(".") == "douyin.com" or cookie.domain.lstrip(".").endswith(".douyin.com")):
            continue
        item: dict[str, Any] = {"name": cookie.name, "value": cookie.value, "domain": cookie.domain, "path": cookie.path or "/", "secure": bool(cookie.secure)}
        if cookie.expires:
            item["expires"] = cookie.expires
        cookies.append(item)
    return cookies


@dataclass
class DouyinResourceClient:
    driver: Any
    secret: bytes

    def __init__(self, driver: Any | None = None, secret: bytes | None = None) -> None:
        self.driver = driver or PlaywrightDouyinDriver()
        self.secret = secret or secrets.token_bytes(32)
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}
        self._images: dict[str, tuple[float, str]] = {}
        self._cache_lock = threading.Lock()
        self._refreshing: set[tuple[Any, ...]] = set()
        self._refresh_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="douyin-refresh")
        self._closed = False

    def close(self) -> None:
        with self._cache_lock:
            self._closed = True
        self._refresh_executor.shutdown(wait=True)
        with self._cache_lock:
            self._cache.clear()
            self._images.clear()
            self._refreshing.clear()
        close = getattr(self.driver, "close", None)
        if close:
            close()

    def capability(self) -> dict[str, Any]:
        return chromium_capability()

    def list_resources(self, account: PlatformAccount, cookie_file: Path, kind: str, offset: int, limit: int, *, force_refresh: bool = False) -> AccountResourceListResponse:
        if kind not in _PAGE_URLS:
            raise ProviderError("resource_not_found", "Unsupported Douyin library type.", 404)
        if kind in {"douyin_works", "douyin_favorites"}:
            title = "Works" if kind == "douyin_works" else "Saved videos"
            resource = self._resource(account, kind, "current", title, None, _PAGE_URLS[kind])
            items = [resource] if offset == 0 else []
            total = 1
        else:
            cache_key = self._cache_key(cookie_file, "resources", account.id, kind, offset, limit)
            cached, stale = self._cache_get(cache_key)
            if not force_refresh and isinstance(cached, AccountResourceListResponse):
                if stale:
                    self._schedule_refresh(
                        cache_key,
                        lambda: self.list_resources(account, cookie_file, kind, offset, limit, force_refresh=True),
                    )
                return cached
            capture = self._observe_with_retry(
                cookie_file,
                _PAGE_URLS[kind],
                _RESPONSE_FAMILIES[kind],
                target_count=offset + limit,
                payload_kind="collections",
                resource_kind=kind,
                force_refresh=force_refresh,
            )
            payloads = capture.payloads
            raw = _collections(payloads)
            resources = [self._resource(account, "douyin_collection", _collection_id(item), _text(item.get("collects_name")) or _text(item.get("name")) or "Untitled collection", _integer(item.get("aweme_count")) or _integer(item.get("item_count")) or _integer(item.get("total_number")), _PAGE_URLS[kind], cover=_image(item.get("cover_url") or item.get("cover"))) for item in raw if _collection_id(item)]
            upstream_total = max([_integer(payload.get("total")) or _integer(payload.get("total_number")) or 0 for payload in payloads] + [len(resources)])
            total = max(upstream_total, len(resources) + (1 if capture.truncated else 0))
            items = resources[offset:offset + limit]
        result = AccountResourceListResponse(items=items, page=PageInfo(offset=offset, limit=limit, total=total, has_more=offset + len(items) < total))
        if kind == "douyin_collections":
            self._cache_put(cache_key, result)
        return result

    def list_entries(self, account: PlatformAccount, cookie_file: Path, resource_id: str, offset: int, limit: int, *, force_refresh: bool = False) -> AccountResourceEntriesResponse:
        kind, external = self._decode(resource_id, account.id)
        cache_key = self._cache_key(cookie_file, "entries", account.id, kind, external, offset, limit)
        cached, stale = self._cache_get(cache_key)
        if not force_refresh and isinstance(cached, AccountResourceEntriesResponse):
            if stale:
                self._schedule_refresh(
                    cache_key,
                    lambda: self.list_entries(account, cookie_file, resource_id, offset, limit, force_refresh=True),
                )
            return cached
        if kind in {"douyin_works", "douyin_favorites"} and external == "current":
            page_url = _PAGE_URLS[kind]
            capture = self._observe_with_retry(cookie_file, page_url, _RESPONSE_FAMILIES[kind], target_count=offset + limit, payload_kind="aweme", resource_kind=kind, force_refresh=force_refresh)
            title = "Works" if kind == "douyin_works" else "Saved videos"
        elif kind == "douyin_collection" and _COLLECTION_ID.fullmatch(external):
            page_url = f"https://www.douyin.com/collection/{external}"
            capture = self._observe_with_retry(cookie_file, page_url, _RESPONSE_FAMILIES[kind], target_count=offset + limit, payload_kind="aweme", resource_kind=kind, force_refresh=force_refresh)
            title = _text(next((p.get("collects_info", {}).get("collects_name") for p in capture.payloads if isinstance(p.get("collects_info"), dict)), None)) or "Collection"
        else:
            raise ProviderError("resource_not_found", "Invalid Douyin resource identifier.", 404)
        payloads = capture.payloads
        raw = _awemes(payloads)
        upstream_total = max([_integer(p.get("total")) or _integer(p.get("total_number")) or 0 for p in payloads] + [len(raw)])
        total = max(upstream_total, len(raw) + (1 if capture.truncated else 0))
        entries = [_entry(item, offset + index + 1) for index, item in enumerate(raw[offset:offset + limit])]
        resource = self._resource(account, kind, external, title, total, page_url)
        result = AccountResourceEntriesResponse(resource=resource, entries=entries, page=PageInfo(offset=offset, limit=limit, total=total, has_more=offset + len(entries) < total))
        self._cache_put(cache_key, result)
        return result

    def video_info(self, cookie_file: Path, canonical_url: str) -> dict[str, Any]:
        capture = self._observe_with_retry(
            cookie_file,
            canonical_url,
            _RESPONSE_FAMILIES["douyin_video"],
            target_count=1,
            payload_kind="detail",
            resource_kind="douyin_video",
            force_refresh=True,
        )
        expected_id = urlparse(canonical_url).path.rstrip("/").rsplit("/", 1)[-1]
        item = next((
            payload.get("aweme_detail")
            for payload in reversed(capture.payloads)
            if isinstance(payload.get("aweme_detail"), dict)
            and _text(payload["aweme_detail"].get("aweme_id")) == expected_id
        ), None)
        if not isinstance(item, dict):
            raise ProviderError("provider_response_invalid", "Douyin returned invalid video data.", 502)
        formats = _video_formats(item, canonical_url)
        if not formats:
            raise ProviderError("provider_response_invalid", "This Douyin video has no downloadable media.", 422)
        author = item.get("author") if isinstance(item.get("author"), dict) else {}
        video = item.get("video") if isinstance(item.get("video"), dict) else {}
        thumbnail_url = self._issue_image(_video_image(video, signed=True))
        return {
            "id": expected_id,
            "title": _text(item.get("desc")) or "Douyin video",
            "webpage_url": canonical_url,
            "extractor": "DouyinBrowser",
            "channel": _text(author.get("nickname")),
            "duration": (_integer(video.get("duration")) or 0) / 1000 or None,
            "thumbnail": thumbnail_url,
            "formats": formats,
        }

    def resolve_image(self, token: str) -> str:
        now = time.monotonic()
        with self._cache_lock:
            self._purge_images(now)
            item = self._images.get(token)
            if item is None:
                raise ProviderError("resource_not_found", "Douyin thumbnail not found or expired.", 404)
            return item[1]

    def _issue_image(self, image_url: str | None) -> str | None:
        if image_url is None:
            return None
        token = secrets.token_urlsafe(24)
        now = time.monotonic()
        with self._cache_lock:
            self._purge_images(now)
            if len(self._images) >= _IMAGE_TOKEN_MAX_ENTRIES:
                oldest = min(self._images, key=lambda key: self._images[key][0])
                self._images.pop(oldest, None)
            self._images[token] = (now + _IMAGE_TOKEN_TTL_SECONDS, image_url)
        return f"/api/media/douyin-thumbnail/{token}"

    def _purge_images(self, now: float) -> None:
        expired = [token for token, (expires_at, _) in self._images.items() if expires_at <= now]
        for token in expired:
            self._images.pop(token, None)

    def warm(self, account: PlatformAccount, cookie_file: Path, *, limit: int = 10) -> None:
        for kind in ("douyin_works", "douyin_favorites"):
            try:
                resource = self.list_resources(account, cookie_file, kind, 0, limit).items[0]
                self.list_entries(account, cookie_file, resource.id, 0, limit, force_refresh=True)
            except (ProviderError, IndexError):
                continue
        try:
            folders = self.list_resources(account, cookie_file, "douyin_collections", 0, limit, force_refresh=True)
        except ProviderError:
            return
        for folder in folders.items:
            try:
                self.list_entries(account, cookie_file, folder.id, 0, limit, force_refresh=True)
            except ProviderError:
                continue

    @staticmethod
    def _cache_key(cookie_file: Path, *parts: Any) -> tuple[Any, ...]:
        try:
            stat = cookie_file.stat()
            fingerprint = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            fingerprint = (0, 0)
        return (*parts, *fingerprint)

    def _cache_get(self, key: tuple[Any, ...]) -> tuple[Any | None, bool]:
        now = time.monotonic()
        with self._cache_lock:
            cached = self._cache.get(key)
            if cached is None:
                return None, False
            created_at, value = cached
            return value, now - created_at > _RESOURCE_CACHE_FRESH_SECONDS

    def _schedule_refresh(self, key: tuple[Any, ...], operation: Any) -> None:
        with self._cache_lock:
            if self._closed or key in self._refreshing:
                return
            self._refreshing.add(key)

        def refresh() -> None:
            try:
                operation()
            except Exception:
                pass
            finally:
                with self._cache_lock:
                    self._refreshing.discard(key)

        try:
            self._refresh_executor.submit(refresh)
        except RuntimeError:
            with self._cache_lock:
                self._refreshing.discard(key)

    def _cache_put(self, key: tuple[Any, ...], value: Any) -> None:
        now = time.monotonic()
        with self._cache_lock:
            if len(self._cache) >= _RESOURCE_CACHE_MAX_ENTRIES:
                oldest = min(self._cache, key=lambda item: self._cache[item][0])
                self._cache.pop(oldest, None)
            self._cache[key] = (now, value)

    def _observe_with_retry(self, cookie_file: Path, page_url: str, families: tuple[str, ...], **kwargs: Any) -> BrowserCapture:
        for attempt in range(2):
            try:
                return self.driver.observe(cookie_file, page_url, families, **kwargs)
            except ProviderError as exc:
                if attempt or exc.code != "provider_response_invalid":
                    raise
        raise AssertionError("unreachable")

    def _resource(self, account: PlatformAccount, kind: str, external: str, title: str, count: int | None, source: str, cover: str | None = None) -> AccountResource:
        return AccountResource(id=self._encode(account.id, kind, external), account_id=account.id, platform="douyin", resource_type=kind, external_id="opaque", title=title, cover_url=cover, owner_name=account.display_name, owner_id=None, item_count=count, is_private=kind != "douyin_works", source_url=source)

    def _encode(self, account_id: str, kind: str, external: str) -> str:
        body = json.dumps([account_id, "douyin", kind, external], separators=(",", ":")).encode()
        signature = hmac.new(self.secret, body, hashlib.sha256).digest()[:16]
        return base64.urlsafe_b64encode(body + signature).decode().rstrip("=")

    def _decode(self, token: str, account_id: str) -> tuple[str, str]:
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            body, signature = raw[:-16], raw[-16:]
            if not hmac.compare_digest(signature, hmac.new(self.secret, body, hashlib.sha256).digest()[:16]):
                raise ValueError
            bound_account, platform, kind, external = json.loads(body)
            if bound_account != account_id or platform != "douyin" or not isinstance(external, str):
                raise ValueError
            return str(kind), external
        except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderError("resource_not_found", "Invalid Douyin resource identifier.", 404) from exc


def _awemes(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in payloads:
        values = payload.get("aweme_list") or payload.get("items") or payload.get("data")
        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                key = _text(item.get("aweme_id") or item.get("id")) or f"missing:{len(result)}"
                if key not in seen:
                    seen.add(key)
                    result.append(item)
    return result


def _payload_records(payloads: list[dict[str, Any]], payload_kind: str) -> list[dict[str, Any]]:
    if payload_kind == "collections":
        return _collections(payloads)
    if payload_kind == "detail":
        return [payload["aweme_detail"] for payload in payloads if isinstance(payload.get("aweme_detail"), dict)]
    return _awemes(payloads)


def _collections(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for payload in payloads:
        values = payload.get("collects_list")

        if isinstance(values, list):
            for item in values:
                if not isinstance(item, dict):
                    continue
                key = _collection_id(item) or f"missing:{len(result)}"
                if key not in seen:
                    seen.add(key)
                    result.append(item)
    return result


def _collection_id(item: dict[str, Any]) -> str:
    value = _text(item.get("collects_id_str")) or _text(item.get("collects_id")) or ""
    return value if _COLLECTION_ID.fullmatch(value) else ""


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "none", "null"}
    return bool(value)


def _safe_media_url(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    url = f"https:{value}" if value.startswith("//") else value
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not any(host.endswith(suffix) for suffix in _MEDIA_SUFFIXES)
    ):
        return None
    return url


def _address_url(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    urls = value.get("url_list")
    if not isinstance(urls, list):
        return None
    return next((safe for candidate in urls if (safe := _safe_media_url(candidate))), None)


def _audio_only_video(video: dict[str, Any]) -> bool:
    addresses = [video.get(key) for key in ("play_addr", "play_addr_h264", "play_addr_265", "play_addr_bytevc1")]
    media_urls = [url for address in addresses if (url := _address_url(address))]
    if any(urlparse(url).path.lower().endswith(".mp3") or "-music-" in (urlparse(url).hostname or "") for url in media_urls):
        return True
    has_video_markers = bool(video.get("bit_rate") or video.get("format") or video.get("play_addr_h264") or video.get("play_addr_265") or video.get("play_addr_bytevc1"))
    return bool(media_urls) and not has_video_markers


def _video_formats(item: dict[str, Any], canonical_url: str) -> list[dict[str, Any]]:
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    if not video or _audio_only_video(video):
        return []
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    bit_rates = video.get("bit_rate")
    if isinstance(bit_rates, list):
        for bitrate in bit_rates:
            if isinstance(bitrate, dict) and isinstance(bitrate.get("play_addr"), dict):
                candidates.append((bitrate["play_addr"], bitrate))
    if not candidates:
        for key, codec in (("play_addr_h264", "h264"), ("play_addr_265", "h265"), ("play_addr_bytevc1", "h265"), ("play_addr", "h264")):
            address = video.get(key)
            if isinstance(address, dict):
                candidates.append((address, {"codec": codec}))

    formats: list[dict[str, Any]] = []
    seen: set[str] = set()
    for address, metadata in candidates:
        media_url = _address_url(address)
        if not media_url or media_url in seen:
            continue
        seen.add(media_url)
        width = _integer(address.get("width")) or _integer(video.get("width"))
        height = _integer(address.get("height")) or _integer(video.get("height"))
        codec = _text(metadata.get("codec")) or ("h265" if _flag(metadata.get("is_bytevc1")) or _flag(metadata.get("is_h265")) else "h264")
        formats.append({
            "format_id": f"browser-{len(formats) + 1}-{height or 0}p-{codec}",
            "url": media_url,
            "ext": "mp4",
            "width": width,
            "height": height,
            "vcodec": codec,
            "acodec": "aac",
            "fps": _integer(metadata.get("FPS") or metadata.get("fps")),
            "filesize": _integer(address.get("data_size")),
            "tbr": (_integer(metadata.get("bit_rate")) or 0) / 1000 or None,
            "http_headers": {"Referer": canonical_url},
        })
    return formats


def _video_image(video: dict[str, Any], *, signed: bool = False) -> str | None:
    normalize = _signed_image if signed else _image
    for key in ("cover", "origin_cover", "dynamic_cover", "animated_cover"):
        url = normalize(video.get(key))
        if url:
            return url
    return None


def _entry(item: dict[str, Any], index: int) -> PlaylistEntry:
    aweme_id = _text(item.get("aweme_id") or item.get("id"))
    video = item.get("video") if isinstance(item.get("video"), dict) else {}
    images = item.get("images") if isinstance(item.get("images"), list) else []
    url = canonicalize_douyin_video_url(f"https://www.douyin.com/video/{aweme_id}") if aweme_id else None
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    image_album = bool(images) and (not video or _audio_only_video(video))
    missing_video = not video or _audio_only_video(video)
    private = _flag(status.get("private_status")) or _flag(status.get("is_private")) or _flag(item.get("private_status")) or _flag(item.get("is_private"))
    restricted = _flag(status.get("is_prohibited")) or _flag(item.get("is_prohibited")) or _flag(status.get("in_reviewing")) or _flag(item.get("in_reviewing"))
    sharing_blocked = status.get("allow_share") is False or status.get("allow_share") == 0 or item.get("allow_share") is False or item.get("allow_share") == 0
    blocked = bool(_flag(item.get("is_delete")) or _flag(status.get("is_delete")) or private or restricted or sharing_blocked or not url)
    unavailable = blocked or missing_video
    if image_album and not blocked:
        reason = "This Douyin item is an image post with background audio, not a video."
    elif unavailable:
        reason = "This Douyin item is deleted, private, or otherwise unavailable."
    else:
        reason = None
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    image_thumbnail = _image(images[0]) if image_album and isinstance(images[0], dict) else None
    return PlaylistEntry(
        index=index,
        id=aweme_id,
        title=_text(item.get("desc")) or "Untitled video",
        url=None if unavailable else url,
        webpage_url=url if (not blocked and (image_album or not unavailable)) else None,
        duration=(_integer(video.get("duration")) or 0) / 1000 or None,
        channel=_text(author.get("nickname")),
        thumbnail_url=_video_image(video) or image_thumbnail,
        entry_type="image_album" if image_album and not blocked else "video",
        is_available=not unavailable,
        unavailable_reason=reason,
    )
