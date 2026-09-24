from __future__ import annotations

import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import requests
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from ytsage.server.api.accounts import _fetch_avatar
from ytsage.server.models import AccountCreateRequest, AccountResource, AccountUpdateRequest, BilibiliQrStartRequest, CreateTaskRequest, PlatformAccount, PlaylistEntry, PlaylistMonitorCreate
from ytsage.server.providers.bilibili import BilibiliIdentity, BilibiliProvider, BilibiliProviderError, BilibiliQrPoll, BilibiliQrSession
from ytsage.server.services.accounts import AccountConflictError, AccountService
from ytsage.server.services.analyzer import _playlist_entry
from ytsage.server.services.storage import Storage
from ytsage.server.services.task_manager import TaskManager


COOKIE = "# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tTRUE\t4102444800\tSESSDATA\ttest-session\n"
REFRESH_COOKIE = COOKIE + ".bilibili.com\tTRUE\t/\tTRUE\t4102444800\tbili_jct\ttest-csrf\n"
DOUYIN_COOKIE = "# Netscape HTTP Cookie File\n.douyin.com\tTRUE\t/\tTRUE\t4102444800\tsessionid\ttest-session\n"


class FakeWarmProvider:
    platform = "douyin"
    cookie_domain = ".douyin.com"

    def __init__(self) -> None:
        self.warmed: list[str] = []
        self.closed = False

    def warm(self, account: PlatformAccount, cookie_file: Path) -> None:
        assert cookie_file.is_file()
        self.warmed.append(account.id)

    def close(self) -> None:
        self.closed = True


@pytest.mark.anyio
async def test_account_service_warms_douyin_accounts_before_start_returns(tmp_path: Path):
    storage = Storage(tmp_path / "state.db")
    account = storage.create_account("douyin-a", "douyin", "A", "accounts/douyin-a/cookies.txt", True)
    cookie_file = tmp_path / "accounts" / account.id / "cookies.txt"
    cookie_file.parent.mkdir(parents=True)
    cookie_file.write_text(DOUYIN_COOKIE, encoding="utf-8")
    provider = FakeWarmProvider()
    service = AccountService(tmp_path, storage, douyin=provider)

    await service.start()

    assert provider.warmed == [account.id]
    assert service._started is True
    await service.stop()
    assert provider.closed is True


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


class CoordinatedResourceProvider:
    platform = "bilibili"
    cookie_domain = ".bilibili.com"

    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.call_counts: dict[str, int] = {}
        self.entered: dict[tuple[str, int], threading.Event] = {}
        self.releases: dict[str, threading.Event] = {}
        self.fail_first: set[str] = set()

    def _call(self, account: PlatformAccount):
        with self.guard:
            ordinal = self.call_counts.get(account.id, 0)
            self.call_counts[account.id] = ordinal + 1
            entered = self.entered.setdefault((account.id, ordinal), threading.Event())
            release = self.releases.setdefault(account.id, threading.Event())
        entered.set()
        if ordinal == 0 and account.id in self.fail_first:
            raise RuntimeError("provider failed")
        release.wait(timeout=5)
        return object()

    def list_resources(self, account: PlatformAccount, *args, **kwargs):
        return self._call(account)

    def list_entries(self, account: PlatformAccount, *args, **kwargs):
        return self._call(account)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, headers: dict | None = None, text: str | None = None) -> None:
        self.content = json.dumps(payload).encode()
        self.text = text if text is not None else self.content.decode()
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

    def post(self, url: str, **kwargs):
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
    account_columns = {row[1] for row in storage._conn.execute("PRAGMA table_info(platform_accounts)").fetchall()}
    assert {"login_method", "auto_refresh", "last_refresh_check_at", "last_refresh_at"} <= account_columns
    assert storage.list_accounts() == []


def test_bilibili_qr_poll_maps_pending_and_scanned_states():
    session = Mock()
    session.get.side_effect = [
        FakeResponse({"code": 0, "data": {"code": 86101, "message": "not scanned"}}),
        FakeResponse({"code": 0, "data": {"code": 86090, "message": "scanned"}}),
    ]
    challenge = BilibiliQrSession(session=session, qr_url="https://example.test/qr", qrcode_key="key", expires_at=9999999999)
    provider = BilibiliProvider()

    assert provider.poll_qr_login(challenge).status == "pending"
    assert provider.poll_qr_login(challenge).status == "scanned"


def test_bilibili_cookie_refresh_check_reads_mozilla_cookie_jar(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(REFRESH_COOKIE, encoding="utf-8")
    provider = BilibiliProvider()

    with patch("ytsage.server.providers.bilibili.requests.get", return_value=FakeResponse({
        "code": 0, "data": {"refresh": False, "timestamp": 123456},
    })) as get:
        required, timestamp = provider.cookie_refresh_required(cookie)

    assert required is False
    assert timestamp == 123456
    assert isinstance(get.call_args.kwargs["cookies"], requests.cookies.RequestsCookieJar)
    assert get.call_args.kwargs["cookies"].get("bili_jct") == "test-csrf"
    assert get.call_args.kwargs["params"]["csrf"] == "test-csrf"


def test_bilibili_cookie_refresh_reads_mozilla_cookie_jar(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(REFRESH_COOKIE, encoding="utf-8")
    provider = BilibiliProvider()
    public_key = Mock()
    public_key.encrypt.return_value = b"encrypted"
    session = requests.Session()

    with (
        patch("ytsage.server.providers.bilibili.serialization.load_pem_public_key", return_value=public_key),
        patch("ytsage.server.providers.bilibili.requests.get", return_value=FakeResponse({}, text='<div id="1-name">refresh-csrf</div>')),
        patch("ytsage.server.providers.bilibili.requests.Session", return_value=session),
        patch.object(session, "post", return_value=FakeResponse({"code": 0, "data": {"refresh_token": "new-token"}})) as post,
    ):
        result = provider.refresh_cookies(cookie, "old-token", 123456)

    assert result.refresh_token == "new-token"
    assert result.old_refresh_token == "old-token"
    assert post.call_args.kwargs["data"]["csrf"] == "test-csrf"


def test_bilibili_cookie_refresh_confirmation_reads_mozilla_cookie_jar(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(REFRESH_COOKIE, encoding="utf-8")
    provider = BilibiliProvider()

    with patch("ytsage.server.providers.bilibili.requests.post", return_value=FakeResponse({"code": 0, "data": {}})) as post:
        provider.confirm_cookie_refresh(cookie, "old-token")

    assert post.call_args.kwargs["data"] == {"csrf": "test-csrf", "refresh_token": "old-token"}


def test_account_refresh_records_check_when_renewal_is_not_required(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    provider = FakeIdentityProvider()
    service = AccountService(tmp_path, storage, provider)  # type: ignore[arg-type]
    account = service.create(AccountCreateRequest(label="One", cookie_content=COOKIE))
    token_path = service.resolve_cookie_file(account.id, require_usable=False).parent / "refresh-token.txt"
    token_path.write_text("refresh-token", encoding="utf-8")
    storage.update_account(account.id, auto_refresh=True, login_method="qr")
    provider.cookie_refresh_required = Mock(return_value=(False, 123))
    provider.refresh_cookies = Mock()

    refreshed = service.refresh(account.id)

    assert refreshed.last_refresh_check_at is not None
    assert refreshed.last_refresh_at is None
    provider.refresh_cookies.assert_not_called()


def test_qr_login_persists_refresh_token_without_exposing_it(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    provider = FakeIdentityProvider()
    session = Mock()
    challenge = BilibiliQrSession(session=session, qr_url="https://example.test/qr", qrcode_key="key", expires_at=9999999999)
    provider.start_qr_login = Mock(return_value=challenge)
    cookie_jar = requests.cookies.RequestsCookieJar()
    cookie_jar.set("SESSDATA", "session", domain=".bilibili.com", path="/")
    cookie_jar.set("bili_jct", "csrf", domain=".bilibili.com", path="/")
    provider.poll_qr_login = Mock(return_value=BilibiliQrPoll("completed", "done", cookie_jar, "secret-refresh-token"))
    service = AccountService(tmp_path, storage, provider)  # type: ignore[arg-type]

    started = service.start_qr_login(BilibiliQrStartRequest(label="QR account"))
    completed = service.poll_qr_login(started.challenge_id)

    assert completed.status == "completed"
    assert completed.account is not None
    assert completed.account.login_method == "qr"
    assert completed.account.auto_refresh is True
    payload = completed.model_dump()
    assert "secret-refresh-token" not in json.dumps(payload)
    token_path = service.resolve_cookie_file(completed.account.id, require_usable=False).parent / "refresh-token.txt"
    assert token_path.read_text(encoding="utf-8") == "secret-refresh-token"


def test_qr_relogin_replaces_credentials_without_changing_account_id(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    provider = FakeIdentityProvider()
    service = AccountService(tmp_path, storage, provider)  # type: ignore[arg-type]
    original = service.create(AccountCreateRequest(label="Existing", cookie_content=COOKIE, make_default=True))
    storage.update_account(original.id, state="invalid", last_error="expired")
    challenge = BilibiliQrSession(session=Mock(), qr_url="https://example.test/qr", qrcode_key="key", expires_at=9999999999)
    provider.start_qr_login = Mock(return_value=challenge)
    cookie_jar = requests.cookies.RequestsCookieJar()
    cookie_jar.set("SESSDATA", "renewed-session", domain=".bilibili.com", path="/")
    cookie_jar.set("bili_jct", "renewed-csrf", domain=".bilibili.com", path="/")
    provider.poll_qr_login = Mock(return_value=BilibiliQrPoll("completed", "done", cookie_jar, "renewed-token"))

    started = service.start_qr_login(BilibiliQrStartRequest(label=original.label, account_id=original.id))
    completed = service.poll_qr_login(started.challenge_id)

    assert completed.account is not None
    assert completed.account.id == original.id
    assert completed.account.is_default is True
    assert completed.account.state == "valid"
    assert completed.account.login_method == "qr"
    assert completed.account.auto_refresh is True
    assert storage.list_accounts()[0].id == original.id
    credential_dir = service.resolve_cookie_file(original.id, require_usable=False).parent
    assert (credential_dir / "refresh-token.txt").read_text(encoding="utf-8") == "renewed-token"


def test_qr_relogin_rejects_a_different_bilibili_identity(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    provider = FakeIdentityProvider()
    service = AccountService(tmp_path, storage, provider)  # type: ignore[arg-type]
    original = service.create(AccountCreateRequest(label="Existing", cookie_content=COOKIE))
    original_cookie = service.resolve_cookie_file(original.id, require_usable=False).read_text(encoding="utf-8")
    challenge = BilibiliQrSession(session=Mock(), qr_url="https://example.test/qr", qrcode_key="key", expires_at=9999999999)
    provider.start_qr_login = Mock(return_value=challenge)
    cookie_jar = requests.cookies.RequestsCookieJar()
    cookie_jar.set("SESSDATA", "other-session", domain=".bilibili.com", path="/")
    cookie_jar.set("bili_jct", "other-csrf", domain=".bilibili.com", path="/")
    provider.poll_qr_login = Mock(return_value=BilibiliQrPoll("completed", "done", cookie_jar, "other-token"))
    provider.next_id = "different-user"

    started = service.start_qr_login(BilibiliQrStartRequest(label=original.label, account_id=original.id))
    with pytest.raises(AccountConflictError, match="does not match"):
        service.poll_qr_login(started.challenge_id)

    assert service.resolve_cookie_file(original.id, require_usable=False).read_text(encoding="utf-8") == original_cookie
    assert not (service.resolve_cookie_file(original.id, require_usable=False).parent / "refresh-token.txt").exists()


def test_imported_cookie_account_does_not_enable_auto_refresh_without_token(tmp_path: Path):
    service = AccountService(tmp_path, Storage(tmp_path / "server.db"), FakeIdentityProvider())  # type: ignore[arg-type]

    account = service.create(AccountCreateRequest(label="Cookie account", cookie_content=COOKIE))

    assert account.login_method == "cookie"
    assert account.auto_refresh is False
    with pytest.raises(AccountConflictError, match="no refresh token"):
        service.refresh(account.id)


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


def test_account_service_rejects_library_access_for_invalid_login(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    account = storage.create_account("account", "bilibili", "A", "accounts/account/cookies.txt")
    storage.update_account(account.id, state="invalid")
    service = AccountService(tmp_path, storage, FakeIdentityProvider())  # type: ignore[arg-type]

    with pytest.raises(AccountConflictError, match="login is invalid"):
        service.resolve_cookie_file(account.id, "bilibili")


def _resource_lock_service(tmp_path: Path, account_ids: tuple[str, ...]) -> tuple[AccountService, CoordinatedResourceProvider]:
    storage = Storage(tmp_path / "resource-locks.db")
    provider = CoordinatedResourceProvider()
    for account_id in account_ids:
        directory = tmp_path / "accounts" / account_id
        directory.mkdir(parents=True)
        (directory / "cookies.txt").write_text(COOKIE, encoding="utf-8")
        storage.create_account(account_id, "bilibili", account_id, f"accounts/{account_id}/cookies.txt")
        storage.update_account(account_id, state="valid")
    return AccountService(tmp_path, storage, providers={"bilibili": provider}), provider  # type: ignore[dict-item]


def test_account_resource_calls_serialize_per_account(tmp_path: Path):
    service, provider = _resource_lock_service(tmp_path, ("account-a",))
    second_started = threading.Event()
    provider.entered[("account-a", 0)] = threading.Event()
    provider.entered[("account-a", 1)] = threading.Event()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.list_resources, "account-a", "created_favorite", 0, 20)
        assert provider.entered[("account-a", 0)].wait(1)
        second = pool.submit(lambda: (second_started.set(), service.list_entries("account-a", "resource", 0, 20))[1])
        assert second_started.wait(1)
        assert not provider.entered[("account-a", 1)].wait(0.1)
        provider.releases["account-a"].set()
        first.result(timeout=1)
        second.result(timeout=1)

    assert provider.entered[("account-a", 1)].is_set()


def test_account_resource_calls_for_different_accounts_run_in_parallel(tmp_path: Path):
    service, provider = _resource_lock_service(tmp_path, ("account-a", "account-b"))
    for account_id in ("account-a", "account-b"):
        provider.entered[(account_id, 0)] = threading.Event()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(service.list_resources, "account-a", "created_favorite", 0, 20)
        second = pool.submit(service.list_resources, "account-b", "created_favorite", 0, 20)
        assert provider.entered[("account-a", 0)].wait(1)
        assert provider.entered[("account-b", 0)].wait(1)
        provider.releases["account-a"].set()
        provider.releases["account-b"].set()
        first.result(timeout=1)
        second.result(timeout=1)


def test_account_resource_lock_releases_after_provider_error(tmp_path: Path):
    service, provider = _resource_lock_service(tmp_path, ("account-a",))
    provider.fail_first.add("account-a")
    provider.entered[("account-a", 0)] = threading.Event()
    provider.entered[("account-a", 1)] = threading.Event()

    with pytest.raises(RuntimeError, match="provider failed"):
        service.list_resources("account-a", "created_favorite", 0, 20)
    provider.releases.setdefault("account-a", threading.Event()).set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(service.list_entries, "account-a", "resource", 0, 20)
        result.result(timeout=1)
    assert provider.entered[("account-a", 1)].is_set()


def test_bilibili_provider_rejects_empty_created_favorite_payload_as_invalid_login(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE, encoding="utf-8")
    provider = BilibiliProvider(http=FakeHttp([{"code": 0, "message": "OK", "data": None}]))
    account = Storage(tmp_path / "server.db").create_account("account", "bilibili", "A", "accounts/account/cookies.txt")
    account = account.model_copy(update={"external_id": "1001"})

    with pytest.raises(BilibiliProviderError) as exc:
        provider.list_resources(account, cookie, "created_favorite", 0, 20)

    assert exc.value.code == "account_login_invalid"
    assert exc.value.status_code == 424


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


def test_bilibili_provider_uses_favorite_detail_total_when_info_count_is_missing(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE, encoding="utf-8")
    http = FakeHttp([{"code": 0, "data": {"total": 41, "info": {"id": 11, "title": "Favorite"}, "medias": [
        {"id": 9, "bvid": "BV123", "title": "Video"},
    ]}}])
    provider = BilibiliProvider(http=http)
    account = Storage(tmp_path / "server.db").create_account("account", "bilibili", "A", "accounts/account/cookies.txt")
    account = account.model_copy(update={"external_id": "1001"})

    page = provider.list_entries(account, cookie, "created_favorite:11", 0, 20)

    assert page.page.total == 41
    assert page.page.has_more is True
    assert page.resource.item_count == 41


def test_account_service_preserves_known_resource_total(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    provider = FakeIdentityProvider()
    service = AccountService(tmp_path, storage, provider)  # type: ignore[arg-type]
    account = service.create(AccountCreateRequest(label="One", cookie_content=COOKIE))
    provider.list_entries = Mock(return_value=BilibiliProvider(http=FakeHttp([{
        "code": 0,
        "data": {"info": {"id": 11, "title": "Favorite"}, "medias": [
            {"id": 9, "bvid": "BV123", "title": "Video"},
        ]},
    }])).list_entries(account, service.resolve_cookie_file(account.id), "created_favorite:11", 0, 20))

    page = service.list_entries(account.id, "created_favorite:11", 0, 20, known_total=41)

    assert page.page.total == 41
    assert page.page.has_more is True
    assert page.resource.item_count == 41


def test_bilibili_provider_classifies_mixed_favorite_entries(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE, encoding="utf-8")
    http = FakeHttp([{"code": 0, "data": {"info": {"id": 11, "media_count": 3}, "medias": [
        {"id": 1, "type": 2, "bvid": "BVsingle", "title": "Single", "page": 1},
        {"id": 2, "type": 2, "bvid": "BVmultipage", "title": "Course", "page": 12},
        {"id": 33, "type": 21, "title": "Favorite collection"},
    ]}}])
    provider = BilibiliProvider(http=http)
    account = Storage(tmp_path / "server.db").create_account("account", "bilibili", "A", "accounts/account/cookies.txt")
    account = account.model_copy(update={"external_id": "1001"})

    entries = provider.list_entries(account, cookie, "created_favorite:11", 0, 20).entries

    assert [entry.entry_type for entry in entries] == ["video", "multipart_video", "favorite_collection"]
    assert entries[1].item_count == 12
    assert entries[2].resource_id == "collected_favorite:33"
    assert entries[2].url == "https://www.bilibili.com/medialist/detail/ml33"
    assert all(entry.is_available for entry in entries)


def test_bilibili_provider_expands_multipart_and_nested_collection(tmp_path: Path):
    cookie = tmp_path / "cookies.txt"
    cookie.write_text(COOKIE, encoding="utf-8")
    http = FakeHttp([
        {"code": 0, "data": {"title": "Course", "owner": {"name": "Teacher"}, "pages": [
            {"page": 1, "part": "Intro", "duration": 60},
            {"page": 2, "part": "Lesson", "duration": 120},
        ]}},
        {"code": 0, "data": {"info": {"id": 33, "title": "Nested", "media_count": 2}, "medias": [
            {"id": 9, "type": 2, "bvid": "BVnested", "title": "Nested video", "page": 1},
            {"id": 10, "type": 2, "bvid": "BVnestedcourse", "title": "Nested course", "page": 2},
        ]}},
        {"code": 0, "data": {"title": "Nested course", "owner": {"name": "Teacher"}, "pages": [
            {"page": 1, "part": "Nested intro", "duration": 30},
            {"page": 2, "part": "Nested lesson", "duration": 45},
        ]}},
    ])
    provider = BilibiliProvider(http=http)
    account = Storage(tmp_path / "server.db").create_account("account", "bilibili", "A", "accounts/account/cookies.txt")
    account = account.model_copy(update={"external_id": "1001"})
    entries = [
        PlaylistEntry(index=1, id="BVmultipage", title="Course", url="https://www.bilibili.com/video/BVmultipage", entry_type="multipart_video", item_count=2),
        PlaylistEntry(index=2, id="favorite:33", title="Saved list", url="https://www.bilibili.com/medialist/detail/ml33", entry_type="favorite_collection", resource_id="collected_favorite:33"),
    ]

    expanded = provider.expand_entries(account, cookie, entries)

    assert [entry.index for entry in expanded] == [1, 2, 3, 4, 5]
    assert [entry.title for entry in expanded] == ["Intro", "Lesson", "Nested video", "Nested intro", "Nested lesson"]
    assert expanded[0].url == "https://www.bilibili.com/video/BVmultipage/?p=1"
    assert expanded[1].part_index == 2
    assert expanded[1].part_count == 2
    assert expanded[2].parent_title == "Saved list"
    assert [(group.title, group.entry_type) for group in expanded[0].group_path] == [("Course", "multipart_video")]
    assert [(group.title, group.entry_type) for group in expanded[2].group_path] == [("Saved list", "favorite_collection")]
    assert [(group.title, group.entry_type) for group in expanded[3].group_path] == [
        ("Saved list", "favorite_collection"),
        ("Nested course", "multipart_video"),
    ]


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
async def test_task_creation_expands_nested_bilibili_entries_before_persisting(tmp_path: Path):
    storage = Storage(tmp_path / "server.db")
    account_service = Mock()
    account_service.resolve_cookie_file.return_value = tmp_path / "cookies.txt"
    account_service.expand_playlist_entries.return_value = [
        PlaylistEntry(index=1, id="BVone", url="https://www.bilibili.com/video/BVone", parent_title="Saved list"),
        PlaylistEntry(index=2, id="BVtwo", url="https://www.bilibili.com/video/BVtwo", parent_title="Saved list"),
    ]
    manager = TaskManager(Mock(config_dir=tmp_path), storage, account_service)
    manager._publish = AsyncMock()
    request = CreateTaskRequest(
        url="https://space.bilibili.com/1001/favlist?fid=33",
        account_id="account",
        playlist_entries=[PlaylistEntry(
            index=1,
            id="favorite:33",
            title="Saved list",
            url="https://www.bilibili.com/medialist/detail/ml33",
            entry_type="favorite_collection",
            resource_id="collected_favorite:33",
        )],
    )

    task = await manager.create_task(request)

    assert [entry["id"] for entry in task.options["playlist_entries"]] == ["BVone", "BVtwo"]
    assert all(entry["parent_title"] == "Saved list" for entry in task.options["playlist_entries"])
    account_service.expand_playlist_entries.assert_called_once()


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


def test_bilibili_provider_normalizes_resource_cover_urls():
    account = PlatformAccount(
        id="account", platform="bilibili", label="Primary", cookie_filename="account.txt",
        created_at="2026-01-01T00:00:00Z", updated_at="2026-01-01T00:00:00Z",
    )

    favorite = BilibiliProvider._favorite_resource(account, {
        "id": 42, "title": "Favorite", "cover": "http://archive.biliimg.com/cover.jpg",
    }, "collected_favorite")
    collection = BilibiliProvider._collection_resource(account, {
        "meta": {"season_id": 84, "name": "Collection", "cover": "//i0.hdslb.com/cover.jpg"},
    }, "collection")

    assert isinstance(favorite, AccountResource)
    assert favorite.cover_url == "https://archive.biliimg.com/cover.jpg"
    assert collection.cover_url == "https://i0.hdslb.com/cover.jpg"


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
