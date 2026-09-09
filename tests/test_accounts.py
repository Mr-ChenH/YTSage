from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from ytsage.server.api.accounts import _fetch_avatar
from ytsage.server.models import AccountCreateRequest, AccountUpdateRequest, CreateTaskRequest, PlaylistEntry, PlaylistMonitorCreate
from ytsage.server.providers.bilibili import BilibiliIdentity, BilibiliProvider, BilibiliProviderError
from ytsage.server.services.accounts import AccountConflictError, AccountService
from ytsage.server.services.analyzer import _playlist_entry
from ytsage.server.services.storage import Storage
from ytsage.server.services.task_manager import TaskManager


COOKIE = "# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tTRUE\t4102444800\tSESSDATA\ttest-session\n"


class FakeIdentityProvider:
    def __init__(self) -> None:
        self.next_id = "1001"

    def verify(self, cookie_file: Path) -> BilibiliIdentity:
        assert "SESSDATA" in cookie_file.read_text(encoding="utf-8")
        return BilibiliIdentity(self.next_id, f"User {self.next_id}", "https://example.test/avatar.jpg", 2)

    def list_resources(self, *args, **kwargs):
        raise NotImplementedError

    def list_entries(self, *args, **kwargs):
        raise NotImplementedError


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, headers: dict | None = None) -> None:
        self.content = json.dumps(payload).encode()
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeHttp:
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payloads.pop(0))


def test_storage_migrates_existing_monitor_schema(tmp_path: Path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE playlist_monitors (id TEXT PRIMARY KEY, url TEXT NOT NULL, title TEXT, enabled INTEGER NOT NULL, interval_minutes INTEGER NOT NULL, download_options_json TEXT NOT NULL, seen_entry_keys_json TEXT NOT NULL, last_checked_at TEXT, next_check_at TEXT NOT NULL, last_error TEXT, last_task_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
    connection.commit()
    connection.close()

    storage = Storage(database)
    columns = {row[1] for row in storage._conn.execute("PRAGMA table_info(playlist_monitors)").fetchall()}

    assert "account_id" in columns
    assert storage.list_accounts() == []


def test_account_service_stores_isolated_credentials_and_default(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    provider = FakeIdentityProvider()
    service = AccountService(tmp_path, storage, provider)  # type: ignore[arg-type]

    first = service.create(AccountCreateRequest(label="Primary", cookie_content=COOKIE))
    provider.next_id = "1002"
    second = service.create(AccountCreateRequest(label="Secondary", cookie_content=COOKIE, make_default=True))

    assert first.external_id == "1001"
    assert second.external_id == "1002"
    assert second.is_default is True
    assert service.get(first.id).is_default is False
    first_path = service.resolve_cookie_file(first.id)
    second_path = service.resolve_cookie_file(second.id)
    assert first_path != second_path
    assert first_path.read_text(encoding="utf-8") == COOKIE
    assert second_path.read_text(encoding="utf-8") == COOKIE


def test_account_service_rejects_duplicate_identity(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    provider = FakeIdentityProvider()
    service = AccountService(tmp_path, storage, provider)  # type: ignore[arg-type]
    service.create(AccountCreateRequest(label="One", cookie_content=COOKIE))

    with pytest.raises(AccountConflictError):
        service.create(AccountCreateRequest(label="Two", cookie_content=COOKIE))

    assert len(service.list()) == 1


def test_account_update_replaces_identity_without_changing_id(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    provider = FakeIdentityProvider()
    service = AccountService(tmp_path, storage, provider)  # type: ignore[arg-type]
    account = service.create(AccountCreateRequest(label="One", cookie_content=COOKIE))
    provider.next_id = "2002"

    updated = service.update(account.id, AccountUpdateRequest(label="Renamed", cookie_content=COOKIE))

    assert updated.id == account.id
    assert updated.label == "Renamed"
    assert updated.external_id == "2002"


def test_deleting_default_account_promotes_remaining_account(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    provider = FakeIdentityProvider()
    service = AccountService(tmp_path, storage, provider)  # type: ignore[arg-type]
    first = service.create(AccountCreateRequest(label="First", cookie_content=COOKIE))
    provider.next_id = "1002"
    second = service.create(AccountCreateRequest(label="Second", cookie_content=COOKIE))

    service.delete(first.id)

    assert service.get(second.id).is_default is True


def test_account_delete_is_blocked_by_monitor(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    provider = FakeIdentityProvider()
    service = AccountService(tmp_path, storage, provider)  # type: ignore[arg-type]
    account = service.create(AccountCreateRequest(label="One", cookie_content=COOKIE))
    request = CreateTaskRequest(url="https://www.bilibili.com/video/BV1test", account_id=account.id)
    storage.create_monitor("monitor", PlaylistMonitorCreate(url=request.url, account_id=account.id, download_options=request))

    with pytest.raises(AccountConflictError):
        service.delete(account.id)


def test_bilibili_provider_lists_created_favorites_with_local_pagination(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE, encoding="utf-8")
    http = FakeHttp([{"code": 0, "data": {"count": 2, "list": [
        {"id": 11, "mid": 1001, "title": "First", "media_count": 8, "attr": 1},
        {"id": 12, "mid": 1001, "title": "Second", "media_count": 3, "attr": 0},
    ]}}])
    provider = BilibiliProvider(http=http)
    account = Storage(tmp_path / "server.db").create_account("account", "bilibili", "A", "accounts/account/cookies.txt")
    account = account.model_copy(update={"external_id": "1001", "display_name": "User"})

    page = provider.list_resources(account, cookie, "created_favorite", 1, 1)

    assert page.page.total == 2
    assert page.items[0].id == "created_favorite:12"
    assert page.items[0].is_private is False


def test_bilibili_provider_lists_collections_and_series(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE, encoding="utf-8")
    http = FakeHttp([{"code": 0, "data": {"items_lists": {"page": {"total": 2},
        "seasons_list": [{"meta": {"season_id": 31, "name": "Course", "total": 8}}],
        "series_list": [{"meta": {"series_id": 42, "name": "Series", "total": 5}}],
    }}}])
    provider = BilibiliProvider(http=http)
    account = Storage(tmp_path / "server.db").create_account("account", "bilibili", "A", "accounts/account/cookies.txt")
    account = account.model_copy(update={"external_id": "1001", "display_name": "User"})

    page = provider.list_resources(account, cookie, "collection", 0, 20)

    assert [item.id for item in page.items] == ["collection:31", "series:42"]
    assert page.items[0].source_url == "https://space.bilibili.com/1001/lists/31"
    assert page.items[1].source_url == "https://www.bilibili.com/list/1001?sid=42"


def test_bilibili_provider_paginates_favorite_entries(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE, encoding="utf-8")
    http = FakeHttp([{"code": 0, "data": {"info": {"id": 11, "title": "Favorite", "media_count": 41}, "medias": [
        {"id": 9, "bvid": "BV123", "title": "Video", "duration": 90, "upper": {"name": "Uploader"}},
    ]}}])
    provider = BilibiliProvider(http=http)
    account = Storage(tmp_path / "server.db").create_account("account", "bilibili", "A", "accounts/account/cookies.txt")
    account = account.model_copy(update={"external_id": "1001", "display_name": "User"})

    page = provider.list_entries(account, cookie, "created_favorite:11", 20, 20)

    assert page.page.total == 41
    assert page.page.has_more is True
    assert page.entries[0].index == 21
    assert page.entries[0].url == "https://www.bilibili.com/video/BV123"
    assert http.calls[0][1]["params"]["pn"] == 2


def test_flat_playlist_marks_invalid_video_unavailable():
    entry = _playlist_entry(1, {"id": "BVinvalid", "url": "BVinvalid", "title": "[已失效视频]", "attr": 1})

    assert entry.is_available is False
    assert entry.url is None


def test_bilibili_provider_marks_invalid_favorite_video_unavailable(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE, encoding="utf-8")
    http = FakeHttp([{"code": 0, "data": {"info": {"id": 11, "media_count": 1}, "medias": [
        {"id": 9, "bvid": "BVinvalid", "title": "已失效视频", "attr": 9},
    ]}}])
    provider = BilibiliProvider(http=http)
    account = Storage(tmp_path / "server.db").create_account("account", "bilibili", "A", "accounts/account/cookies.txt")
    account = account.model_copy(update={"external_id": "1001"})

    entry = provider.list_entries(account, cookie, "created_favorite:11", 0, 20).entries[0]

    assert entry.is_available is False
    assert entry.url is None
    assert entry.webpage_url is None
    assert entry.unavailable_reason


@pytest.mark.anyio
async def test_task_creation_rejects_unavailable_playlist_entries(tmp_path: Path):
    manager = TaskManager(Mock(config_dir=tmp_path), Storage(tmp_path / "server.db"))
    request = CreateTaskRequest(
        url="https://www.bilibili.com/list/watchlater",
        playlist_entries=[PlaylistEntry(index=1, id="BVinvalid", is_available=False)],
    )

    with pytest.raises(ValueError, match="Unavailable playlist entries"):
        await manager.create_task(request)


@pytest.mark.anyio
async def test_task_creation_rejects_arbitrary_cookie_paths(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    manager = TaskManager(Mock(config_dir=tmp_path), storage)

    with pytest.raises(ValueError, match="Custom cookie file paths"):
        await manager.create_task(CreateTaskRequest(url="https://example.com/video", cookie_file=str(tmp_path / "secret.txt")))


@pytest.mark.anyio
async def test_task_restart_preserves_account_binding(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    account_service = Mock()
    account_service.resolve_cookie_file.return_value = tmp_path / "cookies.txt"
    manager = TaskManager(Mock(), storage, account_service)
    manager._publish = AsyncMock()
    original = storage.create_task("original", CreateTaskRequest(url="https://www.bilibili.com/video/BV1test", account_id="account"))
    storage.update_task(original.id, status="failed")

    restarted = await manager.restart_task(original.id)

    assert restarted.options["account_id"] == "account"
    account_service.resolve_cookie_file.assert_called_with("account", "bilibili")


def test_monitor_storage_distinguishes_accounts_for_same_url(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    options = CreateTaskRequest(url="https://www.bilibili.com/watchlater/")
    first = storage.create_monitor("one", PlaylistMonitorCreate(url=options.url, account_id="account-a", download_options=options))
    second = storage.create_monitor("two", PlaylistMonitorCreate(url=options.url, account_id="account-b", download_options=options))

    assert first.account_id == "account-a"
    assert second.account_id == "account-b"


def test_bilibili_provider_normalizes_protocol_relative_avatar(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE, encoding="utf-8")
    provider = BilibiliProvider(http=FakeHttp([{"code": 0, "data": {
        "isLogin": True, "mid": 1001, "uname": "User", "face": "http://i0.hdslb.com/avatar.jpg",
    }}]))

    identity = provider.verify(cookie)

    assert identity.avatar_url == "https://i0.hdslb.com/avatar.jpg"


def test_account_avatar_proxies_bilibili_image_without_cookies():
    upstream = Mock(content=b"image", headers={"Content-Type": "image/jpeg"})
    upstream.raise_for_status.return_value = None

    with patch("ytsage.server.api.accounts.requests.get", return_value=upstream) as get:
        response = _fetch_avatar("http://i0.hdslb.com/avatar.jpg")

    assert response.status_code == 200
    assert response.body == b"image"
    assert response.media_type == "image/jpeg"
    assert get.call_args.args[0] == "https://i0.hdslb.com/avatar.jpg"
    assert "cookies" not in get.call_args.kwargs


def test_account_avatar_rejects_non_bilibili_hosts():
    with pytest.raises(HTTPException) as exc:
        _fetch_avatar("https://example.test/avatar.jpg")

    assert exc.value.status_code == 422


def test_bilibili_provider_rejects_logged_out_identity(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE, encoding="utf-8")
    provider = BilibiliProvider(http=FakeHttp([{"code": 0, "data": {"isLogin": False}}]))

    with pytest.raises(BilibiliProviderError) as exc:
        provider.verify(cookie)

    assert exc.value.code == "account_login_invalid"
