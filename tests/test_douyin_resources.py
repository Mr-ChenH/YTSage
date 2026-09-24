from __future__ import annotations

from pathlib import Path

from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

from ytsage.server.api.accounts import _MAX_IMAGE_BYTES, _fetch_platform_image
from ytsage.server.providers.base import ProviderError
from ytsage.server.models import PlatformAccount
from ytsage.server.providers.douyin_browser import BrowserCapture, DouyinResourceClient, PlaywrightDouyinDriver, chromium_capability, clear_chromium_capability_cache, _capture_page, _dismiss_save_login_dialog, _image


class FakeDriver:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []
        self.closed = False

    def observe(self, cookie_file, page_url, families, **kwargs):
        self.calls.append((cookie_file, page_url, families, kwargs))
        value = self.payloads.pop(0)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, BrowserCapture) else BrowserCapture(value)

    def close(self):
        self.closed = True


@pytest.fixture
def account() -> PlatformAccount:
    return PlatformAccount(id="acct-a", platform="douyin", label="A", external_id="123", display_name="User", state="valid", cookie_filename="unused", created_at="now", updated_at="now")


def aweme(identifier: str, **extra):
    return {"aweme_id": identifier, "desc": f"Video {identifier}", "aweme_type": 0, "video": {"duration": 2500, "cover": {"url_list": ["https://p3.douyinpic.com/cover.jpg"]}}, "author": {"nickname": "Creator"}, **extra}


@pytest.mark.parametrize(
    "kind",
    ("douyin_works", "douyin_favorites"),
)
def test_works_and_favorites_are_virtual_until_entries_opened(account, tmp_path: Path, kind: str):
    driver = FakeDriver([[{"aweme_list": [aweme("1"), aweme("2"), aweme("3")], "total": 3}]])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)

    resource_page = client.list_resources(account, tmp_path / "cookies.txt", kind, 0, 20)

    assert driver.calls == []
    assert resource_page.items[0].external_id == "opaque"
    assert resource_page.items[0].item_count is None

    result = client.list_entries(account, tmp_path / "cookies.txt", resource_page.items[0].id, 1, 1)

    assert len(driver.calls) == 1
    assert driver.calls[0][1] == "https://www.douyin.com/user/self"
    assert driver.calls[0][3]["resource_kind"] == kind
    expected_family = "/aweme/v1/web/aweme/post/" if kind == "douyin_works" else "/aweme/v1/web/aweme/listcollection/"
    assert driver.calls[0][2] == (expected_family,)
    assert result.resource.item_count == 3
    assert result.entries[0].webpage_url == "https://www.douyin.com/video/2"
    assert result.entries[0].url == result.entries[0].webpage_url
    assert result.page.model_dump() == {"offset": 1, "limit": 1, "total": 3, "has_more": True}


def test_resource_entries_use_short_lived_cache_and_cookie_changes_invalidate_it(account, tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("first", encoding="utf-8")
    driver = FakeDriver([
        [{"aweme_list": [aweme("1")], "total": 1}],
        [{"aweme_list": [aweme("2")], "total": 1}],
    ])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)
    resource = client.list_resources(account, cookie, "douyin_favorites", 0, 10).items[0]

    first = client.list_entries(account, cookie, resource.id, 0, 10)
    cached = client.list_entries(account, cookie, resource.id, 0, 10)
    cookie.write_text("second-cookie-version", encoding="utf-8")
    refreshed = client.list_entries(account, cookie, resource.id, 0, 10)

    assert len(driver.calls) == 2
    assert first.entries[0].webpage_url == cached.entries[0].webpage_url
    assert refreshed.entries[0].webpage_url == "https://www.douyin.com/video/2"


def test_collections_list_uses_short_lived_cache(account, tmp_path: Path):
    driver = FakeDriver([[{"collects_list": [{"collects_id_str": "987", "collects_name": "Folder"}]}]])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)

    first = client.list_resources(account, tmp_path / "cookies.txt", "douyin_collections", 0, 10)
    cached = client.list_resources(account, tmp_path / "cookies.txt", "douyin_collections", 0, 10)

    assert len(driver.calls) == 1
    assert cached.items[0].id == first.items[0].id


def test_stale_resource_cache_returns_immediately_and_refreshes_in_background(account, tmp_path: Path):
    driver = FakeDriver([
        [{"aweme_list": [aweme("1")], "total": 1}],
        [{"aweme_list": [aweme("2")], "total": 1}],
    ])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)
    resource = client.list_resources(account, tmp_path / "cookies.txt", "douyin_favorites", 0, 10).items[0]
    first = client.list_entries(account, tmp_path / "cookies.txt", resource.id, 0, 10)

    with patch("ytsage.server.providers.douyin_browser._RESOURCE_CACHE_FRESH_SECONDS", -1):
        stale = client.list_entries(account, tmp_path / "cookies.txt", resource.id, 0, 10)
        client._refresh_executor.shutdown(wait=True)

    refreshed = client.list_entries(account, tmp_path / "cookies.txt", resource.id, 0, 10)

    assert stale.entries[0].webpage_url == first.entries[0].webpage_url
    assert refreshed.entries[0].webpage_url == "https://www.douyin.com/video/2"
    assert len(driver.calls) == 2
    assert driver.calls[1][3]["force_refresh"] is True


def test_warm_populates_first_page_for_each_virtual_library(account, tmp_path: Path):
    driver = FakeDriver([
        [{"aweme_list": [], "has_more": 0}],
        [{"aweme_list": [aweme("1")], "has_more": 0}],
        [{"collects_list": [], "has_more": 0}],
    ])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)

    client.warm(account, tmp_path / "cookies.txt")

    assert [call[3]["resource_kind"] for call in driver.calls] == [
        "douyin_works", "douyin_favorites", "douyin_collections",
    ]
    assert all(call[3]["force_refresh"] is True for call in driver.calls)


def test_collections_use_bound_opaque_ids_and_list_entries(account, tmp_path: Path):
    driver = FakeDriver([[{"collects_list": [{"collects_id_str": "987", "collects_name": "Folder", "aweme_count": 2}]}], [{"aweme_list": [aweme("10"), aweme("11")], "total": 2}]])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)

    folder = client.list_resources(account, tmp_path / "cookies.txt", "douyin_collections", 0, 20).items[0]
    result = client.list_entries(account, tmp_path / "cookies.txt", folder.id, 0, 20)

    assert "987" not in folder.id
    assert folder.resource_type == "douyin_collection"
    assert [entry.webpage_url for entry in result.entries] == ["https://www.douyin.com/video/10", "https://www.douyin.com/video/11"]
    assert driver.calls[1][1] == "https://www.douyin.com/collection/987"
    assert driver.calls[0][2] == ("/aweme/v1/web/collects/list/",)
    assert driver.calls[1][2] == ("/aweme/v1/web/collects/video/list/",)


def test_collections_accept_safe_opaque_ids_and_total_number(account, tmp_path: Path):
    signed_cover = "https://p3.douyinpic.com/folder.jpg?x-signature=secret#fragment"
    driver = FakeDriver([
        [{"collects_list": [{"collects_id": "folder_A-9", "collects_name": "Folder", "total_number": 7, "cover_url": signed_cover}], "total_number": 1}],
        [{"status_code": 0, "aweme_list": [], "total_number": 7}],
    ])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)

    page = client.list_resources(account, tmp_path / "cookies.txt", "douyin_collections", 0, 20)
    result = client.list_entries(account, tmp_path / "cookies.txt", page.items[0].id, 0, 20)

    assert page.page.total == 1
    assert page.items[0].item_count == 7
    assert page.items[0].cover_url == "https://p3.douyinpic.com/folder.jpg"
    assert "secret" not in str(page.model_dump())
    assert driver.calls[1][1] == "https://www.douyin.com/collection/folder_A-9"
    assert result.page.total == 7


@pytest.mark.parametrize("external", ("../secret", "folder/name", "a" * 129, "space value"))
def test_collection_resource_ids_reject_unsafe_external_paths(account, tmp_path: Path, external: str):
    client = DouyinResourceClient(driver=FakeDriver([]), secret=b"x" * 32)
    token = client._encode(account.id, "douyin_collection", external)

    with pytest.raises(ProviderError) as exc:
        client.list_entries(account, tmp_path / "cookies.txt", token, 0, 20)

    assert exc.value.code == "resource_not_found"


def test_empty_works_and_folder_libraries_are_valid(account, tmp_path: Path):
    driver = FakeDriver([
        [{"status_code": 0, "aweme_list": [], "has_more": 0}],
        [{"status_code": 0, "collects_list": [], "has_more": 0}],
    ])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)
    works_id = client.list_resources(account, tmp_path / "cookies.txt", "douyin_works", 0, 20).items[0].id

    works = client.list_entries(account, tmp_path / "cookies.txt", works_id, 0, 20)
    folders = client.list_resources(account, tmp_path / "cookies.txt", "douyin_collections", 0, 20)

    assert works.entries == []
    assert works.resource.item_count == 0
    assert works.page.model_dump() == {"offset": 0, "limit": 20, "total": 0, "has_more": False}
    assert folders.items == []
    assert folders.page.model_dump() == {"offset": 0, "limit": 20, "total": 0, "has_more": False}


def test_resource_ids_reject_tampering_and_cross_account_replay(account, tmp_path: Path):
    client = DouyinResourceClient(driver=FakeDriver([[{"aweme_list": []}]]), secret=b"x" * 32)
    token = client._encode(account.id, "douyin_works", "current")
    other = account.model_copy(update={"id": "acct-b"})

    for invalid_account, invalid_token in ((account, token[:-1] + ("A" if token[-1] != "A" else "B")), (other, token)):
        with pytest.raises(ProviderError) as exc:
            client.list_entries(invalid_account, tmp_path / "cookies.txt", invalid_token, 0, 20)
        assert exc.value.code == "resource_not_found"


class FakeNetworkResponse:
    def __init__(self, payload, url="https://www.douyin.com/aweme/v1/web/aweme/post/?cursor=internal", status=200):
        self.url = url
        self.status = status
        self.request = Mock(resource_type="fetch")
        self._payload = payload

    def json(self):
        return self._payload


class FakeLocator:
    def __init__(self, nodes=()):
        self.nodes = list(nodes)

    def count(self):
        return len(self.nodes)

    def nth(self, index):
        return self.nodes[index]


class FakeNode:
    def __init__(self, page, label, *, visible=True, on_click=None):
        self.page = page
        self.label = label
        self.visible = visible
        self.on_click = on_click
        self.texts = set()
        self.buttons = {}

    def is_visible(self):
        return self.visible

    def click(self):
        self.page.actions.append(self.label)
        if self.on_click:
            self.on_click()

    def press(self, key):
        self.page.actions.append(f"{self.label}:{key}")

    def get_by_text(self, text, exact=False):
        return FakeLocator([FakeNode(self.page, text)] if text in self.texts else [])

    def get_by_role(self, role, **kwargs):
        label = kwargs.get("name")
        return FakeLocator([self.buttons[label]] if role == "button" and label in self.buttons else [])


class FakePage:
    def __init__(self, pages, *, response_url="https://www.douyin.com/aweme/v1/web/aweme/post/?cursor=internal", response_status=200, emit_on="goto", emit_after_ms=None, visible_text=(), visible_after=None, challenge_selector=False, content="<html></html>"):
        self.pages = list(pages)
        self.response_url = response_url
        self.response_status = response_status
        self.emit_on = emit_on
        self.emit_after_ms = emit_after_ms
        self.visible_text = set(visible_text)
        self.visible_after = dict(visible_after or {})
        self.elapsed_ms = 0
        self.challenge_selector = challenge_selector
        self.source = content
        self.callback = None
        self.url = "https://www.douyin.com/user/self"
        self.actions = []
        self.dialogs = []
        self.mouse = Mock()
        self.mouse.wheel.side_effect = self._emit
        self.wheels = 0

    def on(self, event, callback):
        assert event == "response"
        self.callback = callback

    def goto(self, url, **kwargs):
        self.url = url
        if self.emit_on == "goto":
            self._emit()

    def _emit(self, *args):
        self.wheels += 1
        if self.pages:
            self.callback(FakeNetworkResponse(self.pages.pop(0), self.response_url, self.response_status))

    def wait_for_timeout(self, timeout):
        previous = self.elapsed_ms
        self.elapsed_ms += timeout
        if self.emit_after_ms is not None and previous < self.emit_after_ms <= self.elapsed_ms:
            self._emit()

    def content(self):
        return self.source

    def get_by_text(self, text, exact=False):
        on_click = self._emit if self.emit_on == text else None
        is_visible = text in self.visible_text or self.elapsed_ms >= self.visible_after.get(text, float("inf"))
        nodes = [FakeNode(self, text, on_click=on_click)] if is_visible else []
        return FakeLocator(nodes)

    def get_by_role(self, role, **kwargs):
        return FakeLocator(self.dialogs if role == "dialog" else [])

    def locator(self, selector):
        nodes = [FakeNode(self, "challenge")] if self.challenge_selector else []
        return FakeLocator(nodes)



class FakePlaywright:
    def __init__(self, page):
        self.page = page
        self.context = Mock()
        self.context.new_page.return_value = page
        self.browser = Mock()
        self.browser.new_context.return_value = self.context
        self.chromium = Mock()
        self.chromium.launch.return_value = self.browser

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


def _cookie_file(tmp_path: Path) -> Path:
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    return cookie


def _observe(page: FakePage, tmp_path: Path, family: str, *, resource_kind="douyin_works", payload_kind="aweme", target_count=1):
    runtime = FakePlaywright(page)
    driver = PlaywrightDouyinDriver(playwright_factory=lambda: runtime)
    capture = driver.observe(
        _cookie_file(tmp_path),
        "https://www.douyin.com/user/self",
        (family,),
        target_count=target_count,
        payload_kind=payload_kind,
        resource_kind=resource_kind,
    )
    return capture, runtime


def test_driver_scrolls_until_deduplicated_target_and_cleans_up(tmp_path: Path):
    pages = [
        {"status_code": 0, "aweme_list": [aweme(str(index)) for index in range(1, 11)], "has_more": True},
        {"status_code": 0, "aweme_list": [aweme(str(index)) for index in range(6, 16)], "has_more": True},
        {"status_code": 0, "aweme_list": [aweme(str(index)) for index in range(16, 26)], "has_more": True},
    ]
    page = FakePage(pages)
    runtime = FakePlaywright(page)
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    driver = PlaywrightDouyinDriver(playwright_factory=lambda: runtime)

    capture = driver.observe(cookie, "https://www.douyin.com/user/self", ("/aweme/v1/web/aweme/post/",), target_count=25, payload_kind="aweme")

    assert len(capture.payloads) == 3
    assert capture.truncated is True
    assert page.mouse.wheel.call_count == 2
    runtime.context.close.assert_called_once_with()
    runtime.browser.close.assert_called_once_with()


def test_capture_page_reuses_current_scroll_history_for_next_page():
    first_page = {"status_code": 0, "aweme_list": [aweme(str(index)) for index in range(10)], "has_more": 1}
    second_page = {"status_code": 0, "aweme_list": [aweme(str(index)) for index in range(10, 20)], "has_more": 1}
    page = FakePage(
        [second_page],
        response_url="https://www.douyin.com/aweme/v1/web/aweme/listcollection/?signed=hidden",
        emit_on="wheel",
    )

    capture = _capture_page(
        page,
        "https://www.douyin.com/user/self",
        ("/aweme/v1/web/aweme/listcollection/",),
        target_count=20,
        payload_kind="aweme",
        resource_kind="douyin_favorites",
        timeout_ms=20_000,
        reuse_profile=True,
        seed_payloads=[first_page],
        continue_current=True,
    )

    assert len(capture.payloads) == 2
    assert page.mouse.wheel.call_count == 1
    assert page.actions == []


def test_capture_page_refreshes_works_through_visible_tab():
    family = "/aweme/v1/web/aweme/post/"
    page = FakePage(
        [{"status_code": 0, "aweme_list": [], "has_more": 0}],
        response_url=f"https://www.douyin.com{family}?signed=hidden",
        emit_on="\u4f5c\u54c1",
        visible_text=("\u4f5c\u54c1",),
    )

    capture = _capture_page(
        page,
        "https://www.douyin.com/user/self",
        (family,),
        target_count=10,
        payload_kind="aweme",
        resource_kind="douyin_works",
        timeout_ms=20_000,
        reuse_profile=True,
    )

    assert capture.payloads[0]["aweme_list"] == []
    assert page.actions == ["\u4f5c\u54c1"]


def test_driver_navigates_visible_favorites_video_tab_and_captures_listcollection(tmp_path: Path):
    family = "/aweme/v1/web/aweme/listcollection/"
    page = FakePage(
        [{"status_code": 0, "aweme_list": [aweme("1")], "has_more": 0}],
        response_url=f"https://www.douyin.com{family}?signed=hidden",
        emit_on="\u89c6\u9891",
        visible_text=("\u6536\u85cf", "\u89c6\u9891"),
    )

    capture, _ = _observe(page, tmp_path, family, resource_kind="douyin_favorites")

    assert page.actions == ["\u6536\u85cf", "\u89c6\u9891"]
    assert capture.payloads[0]["aweme_list"][0]["aweme_id"] == "1"


def test_driver_waits_for_async_library_subtab(tmp_path: Path):
    family = "/aweme/v1/web/aweme/listcollection/"
    page = FakePage(
        [{"status_code": 0, "aweme_list": [], "has_more": 0}],
        response_url=f"https://www.douyin.com{family}?signed=hidden",
        emit_on="\u89c6\u9891",
        visible_text=("\u6536\u85cf",),
        visible_after={"\u89c6\u9891": 3600},
    )

    capture, _ = _observe(page, tmp_path, family, resource_kind="douyin_favorites")

    assert page.actions == ["\u6536\u85cf", "\u89c6\u9891"]
    assert capture.payloads == [{"status_code": 0, "aweme_list": [], "has_more": 0}]


def test_driver_navigates_visible_collection_folder_tab_and_captures_folders(tmp_path: Path):
    family = "/aweme/v1/web/collects/list/"
    page = FakePage(
        [{"status_code": 0, "collects_list": [{"collects_id_str": "1"}], "has_more": 0}],
        response_url=f"https://www.douyin.com{family}?signed=hidden",
        emit_on="\u6536\u85cf\u5939",
        visible_text=("\u6536\u85cf", "\u6536\u85cf\u5939"),
    )

    capture, _ = _observe(page, tmp_path, family, resource_kind="douyin_collections", payload_kind="collections")

    assert page.actions == ["\u6536\u85cf", "\u6536\u85cf\u5939"]
    assert capture.payloads[0]["collects_list"][0]["collects_id_str"] == "1"


def test_driver_waits_for_delayed_first_folder_response_before_scrolling(tmp_path: Path):
    family = "/aweme/v1/web/collects/list/"
    page = FakePage(
        [{"status_code": 0, "collects_list": [], "has_more": 0}],
        response_url=f"https://www.douyin.com{family}?signed=hidden",
        emit_on="delayed",
        emit_after_ms=7_000,
        visible_text=("\u6536\u85cf", "\u6536\u85cf\u5939"),
    )

    capture, _ = _observe(page, tmp_path, family, resource_kind="douyin_collections", payload_kind="collections")

    assert capture.payloads == [{"status_code": 0, "collects_list": [], "has_more": 0}]
    assert page.mouse.wheel.call_count == 0


def test_driver_dismisses_only_exact_visible_save_login_dialog(tmp_path: Path):
    page = FakePage([{"status_code": 0, "aweme_list": []}])
    dialog = FakeNode(page, "save-dialog")
    dialog.texts.add("\u4fdd\u5b58\u767b\u5f55\u4fe1\u606f")
    dialog.buttons["\u6682\u4e0d\u4fdd\u5b58"] = FakeNode(page, "\u6682\u4e0d\u4fdd\u5b58")
    page.dialogs.append(dialog)

    capture, _ = _observe(page, tmp_path, "/aweme/v1/web/aweme/post/")

    assert capture.payloads == [{"status_code": 0, "aweme_list": []}]
    assert page.actions == ["\u6682\u4e0d\u4fdd\u5b58"]


def test_driver_dismisses_unroled_save_login_dialog():
    page = FakePage(
        [],
        visible_text=("\u4fdd\u5b58\u767b\u5f55\u4fe1\u606f", "\u53d6\u6d88"),
    )

    assert _dismiss_save_login_dialog(page) is True
    assert page.actions == ["\u53d6\u6d88"]


def test_driver_ignores_captcha_words_in_page_source(tmp_path: Path):
    page = FakePage(
        [{"status_code": 0, "aweme_list": []}],
        content='<script>const captcha = "verifycenter";</script>',
    )

    capture, _ = _observe(page, tmp_path, "/aweme/v1/web/aweme/post/")

    assert capture.payloads == [{"status_code": 0, "aweme_list": []}]


@pytest.mark.parametrize("visible_text, challenge_selector", [("\u4eba\u673a\u9a8c\u8bc1", False), (None, True)])
def test_driver_rejects_visible_challenge_ui(tmp_path: Path, visible_text: str | None, challenge_selector: bool):
    page = FakePage([], visible_text=(() if visible_text is None else (visible_text,)), challenge_selector=challenge_selector)

    with pytest.raises(ProviderError) as exc:
        _observe(page, tmp_path, "/aweme/v1/web/aweme/post/")

    assert exc.value.code == "provider_risk_control"
    assert page.actions == []


def test_driver_accepts_status_zero_empty_libraries(tmp_path: Path):
    page = FakePage([{"status_code": 0, "aweme_list": [], "has_more": 0}])

    capture, _ = _observe(page, tmp_path, "/aweme/v1/web/aweme/post/", target_count=20)

    assert capture.payloads == [{"status_code": 0, "aweme_list": [], "has_more": 0}]
    assert capture.truncated is False


@pytest.mark.parametrize(
    "status, expected_code",
    (
        (401, "account_login_invalid"),
        (403, "provider_risk_control"),
        (429, "provider_risk_control"),
        (461, "provider_risk_control"),
        (471, "provider_risk_control"),
        (408, "provider_timeout"),
        (504, "provider_timeout"),
        (500, "provider_unavailable"),
        (404, "provider_response_invalid"),
    ),
)
def test_driver_classifies_target_http_failures_without_exposing_body(tmp_path: Path, status: int, expected_code: str):
    page = FakePage([{"status_code": 0, "message": "secret upstream detail"}], response_status=status)

    with pytest.raises(ProviderError) as exc:
        _observe(page, tmp_path, "/aweme/v1/web/aweme/post/")

    assert exc.value.code == expected_code
    assert "secret" not in str(exc.value).lower()


@pytest.mark.parametrize(
    "payload, expected_code",
    (
        ({"status_code": 461, "status_msg": "secret"}, "provider_risk_control"),
        ({"status_code": 471}, "provider_risk_control"),
        ({"status_code": 2156}, "provider_risk_control"),
        ({"status_code": 4031}, "provider_risk_control"),
        ({"status_code": 9999, "status_msg": "captcha secret"}, "provider_risk_control"),
        ({"status_code": 1041, "status_msg": "secret"}, "account_login_invalid"),
        ({"status_code": 9999, "has_login": False}, "account_login_invalid"),
        ({"status_code": 9999, "status_msg": "login expired secret"}, "account_login_invalid"),
        ({"aweme_list": []}, "provider_response_invalid"),
        ({"status_code": "not-an-integer", "aweme_list": []}, "provider_response_invalid"),
        ({"status_code": 10001, "status_msg": "secret"}, "provider_response_invalid"),
    ),
)
def test_driver_classifies_target_payload_failures_without_exposing_text(tmp_path: Path, payload: dict, expected_code: str):
    page = FakePage([payload])

    with pytest.raises(ProviderError) as exc:
        _observe(page, tmp_path, "/aweme/v1/web/aweme/post/")

    assert exc.value.code == expected_code
    assert "secret" not in str(exc.value).lower()


def test_driver_rejects_endpoint_error_payload(tmp_path: Path):
    page = FakePage([{"status_code": 10001, "status_msg": "sensitive upstream detail"}])

    with pytest.raises(ProviderError) as exc:
        _observe(page, tmp_path, "/aweme/v1/web/aweme/post/")

    assert exc.value.code == "provider_response_invalid"
    assert "sensitive upstream detail" not in str(exc.value)


def test_driver_rejects_error_after_successful_partial_page(tmp_path: Path):
    page = FakePage([
        {"status_code": 0, "aweme_list": [aweme("1")], "has_more": 1},
        {"status_code": 10001, "status_msg": "sensitive upstream detail"},
    ])

    with pytest.raises(ProviderError) as exc:
        _observe(page, tmp_path, "/aweme/v1/web/aweme/post/", target_count=2)

    assert exc.value.code == "provider_response_invalid"


def test_driver_hard_caps_scrolls_when_duplicates_never_reach_target(tmp_path: Path):
    duplicate_page = {"status_code": 0, "aweme_list": [aweme("1")], "has_more": True}
    page = FakePage([duplicate_page] * 50)
    runtime = FakePlaywright(page)
    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    driver = PlaywrightDouyinDriver(playwright_factory=lambda: runtime)

    capture = driver.observe(cookie, "https://www.douyin.com/user/self", ("/aweme/v1/web/aweme/post/",), target_count=10, payload_kind="aweme")

    assert capture.truncated is True
    assert page.mouse.wheel.call_count == 40


def test_high_offset_requests_enough_deduplicated_records_and_reports_truncation(account, tmp_path: Path):
    items = [aweme(str(index)) for index in range(1, 56)]
    driver = FakeDriver([BrowserCapture([{"aweme_list": items, "has_more": True}], truncated=True)])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)
    token = client._encode(account.id, "douyin_works", "current")

    result = client.list_entries(account, tmp_path / "cookies.txt", token, 50, 5)

    assert [entry.id for entry in result.entries] == ["51", "52", "53", "54", "55"]
    assert driver.calls[0][3]["target_count"] == 55
    assert result.page.has_more is True
    assert result.page.total == 56


def test_nonstandard_aweme_types_with_video_payloads_remain_available(account, tmp_path: Path):
    media = {
        "duration": 2500,
        "format": "mp4",
        "play_addr": {"url_list": ["https://v26-web.douyinvod.com/video"]},
        "cover": {"url_list": ["https://p3.douyinpic.com/cover.jpg"]},
    }
    audio_only = {
        "duration": 2500,
        "play_addr": {"url_list": ["https://sf11-cdn-tos.douyinstatic.com/audio.mp3"]},
    }
    driver = FakeDriver([[{"aweme_list": [
        aweme("61", aweme_type=61, video=media),
        aweme("68", aweme_type=68, video=media),
        aweme("69", aweme_type=68, video=audio_only),
    ], "total": 3}]])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)
    token = client._encode(account.id, "douyin_favorites", "current")

    entries = client.list_entries(account, tmp_path / "cookies.txt", token, 0, 20).entries

    assert [entry.is_available for entry in entries] == [True, True, False]
    assert [entry.url for entry in entries[:2]] == [
        "https://www.douyin.com/video/61",
        "https://www.douyin.com/video/68",
    ]
    assert entries[2].url is None
    assert "douyinvod" not in str([entry.model_dump() for entry in entries])


def test_video_info_uses_page_generated_detail_response(account, tmp_path: Path):
    video = {
        "duration": 2500,
        "width": 1080,
        "height": 1920,
        "format": "mp4",
        "bit_rate": [{
            "gear_name": "normal_1080_0",
            "bit_rate": 900000,
            "FPS": 30,
            "play_addr": {
                "url_list": ["https://v26-web.douyinvod.com/video?signature=opaque"],
                "width": 1080,
                "height": 1920,
                "data_size": 1024,
            },
        }],
        "cover": {"url_list": ["https://p3.douyinpic.com/cover.jpg?signature=hidden"]},
    }
    driver = FakeDriver([[{"status_code": 0, "aweme_detail": {
        "aweme_id": "1234567890123456789",
        "desc": "Saved video",
        "video": video,
        "author": {"nickname": "Creator"},
    }}]])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)
    canonical = "https://www.douyin.com/video/1234567890123456789"

    info = client.video_info(tmp_path / "cookies.txt", canonical)

    assert driver.calls[0][1] == canonical
    assert driver.calls[0][2] == ("/aweme/v1/web/aweme/detail/",)
    assert driver.calls[0][3]["payload_kind"] == "detail"
    assert driver.calls[0][3]["resource_kind"] == "douyin_video"
    assert info["title"] == "Saved video"
    assert info["formats"][0]["format_id"] == "browser-1-1920p-h264"
    assert info["formats"][0]["url"].endswith("signature=opaque")
    assert info["thumbnail"].startswith("/api/media/douyin-thumbnail/")
    assert "signature" not in info["thumbnail"]
    token = info["thumbnail"].rsplit("/", 1)[-1]
    assert client.resolve_image(token).endswith("signature=hidden")


def test_unavailable_private_deleted_and_image_items_have_no_media_urls(account, tmp_path: Path):
    items = [
        aweme("1", is_delete=True),
        aweme("2", status={"is_delete": True}),
        aweme("3", status={"private_status": 1}),
        aweme("4", status={"is_prohibited": True}),
        aweme("5", status={"in_reviewing": True}),
        aweme("6", status={"allow_share": False}),
        {"aweme_id": "7", "desc": "Images", "aweme_type": 68, "images": [{"url_list": ["https://p3.douyinpic.com/image.jpg"]}], "video": {"duration": 2500, "play_addr": {"url_list": ["https://sf11-cdn-tos.douyinstatic.com/audio.mp3"]}}},
        {"aweme_id": "8", "desc": "Missing video", "aweme_type": 0},
    ]
    driver = FakeDriver([[{"aweme_list": items, "total": len(items)}]])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)
    token = client._encode(account.id, "douyin_favorites", "current")

    entries = client.list_entries(account, tmp_path / "cookies.txt", token, 0, 20).entries

    blocked_entries = entries[:6] + entries[7:]
    assert all(not entry.is_available and entry.url is None and entry.webpage_url is None for entry in blocked_entries)
    image_album = entries[6]
    assert image_album.entry_type == "image_album"
    assert image_album.is_available is False
    assert image_album.url is None
    assert image_album.webpage_url == "https://www.douyin.com/video/7"
    assert image_album.thumbnail_url == "https://p3.douyinpic.com/image.jpg"
    assert image_album.unavailable_reason == "This Douyin item is an image post with background audio, not a video."
    assert "douyinpic.com" in (entries[0].thumbnail_url or "")
    assert "play_addr" not in str([entry.model_dump() for entry in entries])


def test_image_normalization_strips_query_and_fragment_before_models_and_proxy(account, tmp_path: Path):
    signed = "https://p3.douyinpic.com/cover.jpg?x-signature=secret&cursor=hidden#fragment"
    assert _image({"url_list": [signed]}) == "https://p3.douyinpic.com/cover.jpg"
    driver = FakeDriver([[{"status_code": 0, "aweme_list": [aweme("1", video={"duration": 2500, "cover": {"url_list": [signed]}})]}]])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)
    token = client._encode(account.id, "douyin_works", "current")

    entry = client.list_entries(account, tmp_path / "cookies.txt", token, 0, 20).entries[0]

    assert entry.thumbnail_url == "https://p3.douyinpic.com/cover.jpg"
    image = ImageResponse(headers={"Content-Type": "image/jpeg"}, chunks=(b"image",))
    with patch("ytsage.server.api.accounts.requests.get", return_value=image) as get:
        _fetch_platform_image("douyin", entry.thumbnail_url)
    assert get.call_args.args[0] == "https://p3.douyinpic.com/cover.jpg"
    assert "secret" not in str(entry.model_dump())
    assert "cursor" not in str(entry.model_dump())


@pytest.mark.parametrize("url", (
    "http://p3.douyinpic.com/cover.jpg",
    "https://user@p3.douyinpic.com/cover.jpg",
    "https://p3.douyinpic.com:444/cover.jpg",
    "https://evil.example/cover.jpg",
))
def test_image_normalization_keeps_strict_authority_validation(url: str):
    assert _image(url) is None


def test_resource_client_retries_one_transient_invalid_browser_response(account, tmp_path: Path):
    driver = FakeDriver([
        ProviderError("provider_response_invalid", "Transient page navigation failure.", 502),
        [{"status_code": 0, "aweme_list": [aweme("1")], "has_more": 0}],
    ])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)
    resource = client.list_resources(account, tmp_path / "cookies.txt", "douyin_favorites", 0, 10).items[0]

    result = client.list_entries(account, tmp_path / "cookies.txt", resource.id, 0, 10)

    assert [entry.id for entry in result.entries] == ["1"]
    assert len(driver.calls) == 2


def test_driver_errors_are_sanitized_and_cleanup_is_deterministic(account, tmp_path: Path):
    driver = FakeDriver([ProviderError("provider_risk_control", "Douyin requires interactive verification.", 503)])
    client = DouyinResourceClient(driver=driver, secret=b"x" * 32)

    resource = client.list_resources(account, tmp_path / "secret-cookie-path.txt", "douyin_works", 0, 20).items[0]
    assert driver.calls == []
    with pytest.raises(ProviderError) as exc:
        client.list_entries(account, tmp_path / "secret-cookie-path.txt", resource.id, 0, 20)
    assert exc.value.code == "provider_risk_control"
    assert len(driver.calls) == 1
    assert "secret-cookie-path" not in str(exc.value)
    client.close()
    assert driver.closed is True


def test_chromium_capability_requires_executable_binary(tmp_path: Path):
    clear_chromium_capability_cache()
    runtime = Mock()
    runtime.chromium.executable_path = str(tmp_path / "missing-chromium")
    starter = Mock()
    starter.start.return_value = runtime
    with patch("playwright.sync_api.sync_playwright", return_value=starter):
        capability = chromium_capability()
    assert capability == {"available": False, "engine": "playwright-chromium"}
    runtime.chromium.launch.assert_not_called()
    runtime.stop.assert_called_once_with()


def test_chromium_capability_requires_successful_launch_and_caches(tmp_path: Path):
    executable = tmp_path / "chromium"
    executable.write_text("binary", encoding="utf-8")
    executable.chmod(0o755)
    clear_chromium_capability_cache()
    runtime = Mock()
    runtime.chromium.executable_path = str(executable)
    runtime.chromium.launch.side_effect = RuntimeError("missing dependency secret")
    starter = Mock()
    starter.start.return_value = runtime
    with patch("playwright.sync_api.sync_playwright", return_value=starter):
        first = chromium_capability()
        second = chromium_capability()
    assert first == second == {"available": False, "engine": "playwright-chromium"}
    runtime.chromium.launch.assert_called_once_with(channel="chromium", headless=True)
    runtime.stop.assert_called_once_with()


def test_chromium_capability_closes_successful_probe(tmp_path: Path):
    executable = tmp_path / "chromium"
    executable.write_text("binary", encoding="utf-8")
    executable.chmod(0o755)
    clear_chromium_capability_cache()
    runtime = Mock()
    runtime.chromium.executable_path = str(executable)
    browser = Mock()
    runtime.chromium.launch.return_value = browser
    starter = Mock()
    starter.start.return_value = runtime
    with patch("playwright.sync_api.sync_playwright", return_value=starter):
        capability = chromium_capability()
    assert capability == {"available": True, "engine": "playwright-chromium"}
    browser.close.assert_called_once_with()
    runtime.stop.assert_called_once_with()


def test_docker_uses_shared_playwright_browser_path():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim-bookworm AS runtime" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH=/ms-playwright" in dockerfile
    assert "python -m playwright install --no-shell chromium" in dockerfile
    chromium_packages = (
        "libasound2", "libatk-bridge2.0-0", "libatk1.0-0", "libatspi2.0-0", "libcairo2", "libcups2",
        "libdbus-1-3", "libdrm2", "libgbm1", "libglib2.0-0", "libnspr4", "libnss3", "libpango-1.0-0",
        "libx11-6", "libxcb1", "libxcomposite1", "libxdamage1", "libxext6", "libxfixes3", "libxkbcommon0", "libxrandr2",
    )
    for package in chromium_packages:
        assert package in dockerfile
    assert "ytsage:ytsage /config /downloads /app /ms-playwright" in dockerfile


class ImageResponse:
    def __init__(self, *, status=200, headers=None, chunks=()):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        return iter(self._chunks)

    def close(self):
        self.closed = True


def test_image_proxy_revalidates_redirect_host():
    redirect = ImageResponse(status=302, headers={"Location": "https://evil.example/image.jpg"})
    with patch("ytsage.server.api.accounts.requests.get", return_value=redirect) as get:
        with pytest.raises(HTTPException) as exc:
            _fetch_platform_image("douyin", "https://p3.douyinpic.com/image.jpg")
    assert exc.value.status_code == 422
    assert get.call_count == 1
    assert redirect.closed is True


def test_image_proxy_accepts_validated_redirect_and_bounded_image():
    redirect = ImageResponse(status=302, headers={"Location": "https://i1.hdslb.com/final.jpg"})
    image = ImageResponse(headers={"Content-Type": "image/jpeg"}, chunks=(b"abc", b"def"))
    with patch("ytsage.server.api.accounts.requests.get", side_effect=[redirect, image]) as get:
        response = _fetch_platform_image("bilibili", "https://i0.hdslb.com/start.jpg")
    assert response.body == b"abcdef"
    assert get.call_count == 2
    assert all(call.kwargs["allow_redirects"] is False and call.kwargs["stream"] is True for call in get.call_args_list)


def test_image_proxy_rejects_oversized_stream():
    image = ImageResponse(headers={"Content-Type": "image/jpeg"}, chunks=(b"x" * _MAX_IMAGE_BYTES, b"y"))
    with patch("ytsage.server.api.accounts.requests.get", return_value=image):
        with pytest.raises(HTTPException) as exc:
            _fetch_platform_image("douyin", "https://p3.douyinpic.com/image.jpg")
    assert exc.value.status_code == 502
    assert "large" in exc.value.detail
    assert image.closed is True
