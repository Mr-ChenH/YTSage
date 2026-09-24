from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import HTTPException

from ytsage.server.api.analysis import create_analysis_router
from ytsage.server.api.tasks import create_tasks_router
from ytsage.server.models import AccountCreateRequest, AccountUpdateRequest, AnalyzeRequest, CreateTaskRequest, HistoryEntry, PlaylistEntry
from ytsage.server.providers.base import PlatformIdentity
from ytsage.server.providers.douyin import canonicalize_douyin_video_url, DouyinProvider, DouyinProviderError
from ytsage.server.services.accounts import AccountService
from ytsage.server.services.analyzer import analyze
from ytsage.server.services.cookies import cookie_domain_for_profile, cookie_names, cookie_profile_for_url, normalize_cookies
from ytsage.server.services.douyin_proofs import DouyinDownloadProofStore, DouyinProofError
from ytsage.server.services.storage import Storage
from ytsage.server.services.task_manager import TaskManager


DOUYIN_HEADER = "sessionid=session-value; ttwid=device-value; UIFID=fingerprint; custom_future_cookie=kept"


class FakeResponse:
    def __init__(self, payload: dict | None = None, *, status_code: int = 200, text: str | None = None) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(payload)

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeDouyinProvider:
    platform = "douyin"
    cookie_domain = ".douyin.com"
    allow_unverified_import = True

    def __init__(self, result: PlatformIdentity | Exception) -> None:
        self.result = result

    def validate_cookie_file(self, cookie_file: Path) -> None:
        assert "custom_future_cookie" in cookie_names(cookie_file)

    def verify(self, cookie_file: Path) -> PlatformIdentity:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_douyin_cookie_header_preserves_all_cookie_pairs() -> None:
    normalized = normalize_cookies(DOUYIN_HEADER, ".douyin.com")

    assert normalized is not None
    assert "\tsessionid\tsession-value" in normalized
    assert "\tttwid\tdevice-value" in normalized
    assert "\tUIFID\tfingerprint" in normalized
    assert "\tcustom_future_cookie\tkept" in normalized


def test_cookie_profile_recognizes_only_real_douyin_domains() -> None:
    assert cookie_profile_for_url("https://www.douyin.com/video/123") == "douyin"
    assert cookie_profile_for_url("https://v.douyin.com/example/") == "douyin"
    assert cookie_profile_for_url("https://live.iesdouyin.com/example/") == "douyin"
    assert cookie_profile_for_url("https://notdouyin.com/video/123") == "default"
    assert cookie_profile_for_url("https://evilbilibili.com/video/123") == "default"


def test_douyin_video_canonicalization_rejects_hostile_authorities() -> None:
    media_id = "1234567890123456789"
    canonical = f"https://www.douyin.com/video/{media_id}"

    assert canonicalize_douyin_video_url(canonical) == canonical
    assert canonicalize_douyin_video_url(f"https://m.douyin.com/share/video/{media_id}/") == canonical
    assert canonicalize_douyin_video_url(f"https://www.douyin.com:443/video/{media_id}") == canonical
    for hostile in (
        f"http://www.douyin.com/video/{media_id}",
        f"ftp://www.douyin.com/video/{media_id}",
        f"https://user@www.douyin.com/video/{media_id}",
        f"https://user:password@www.douyin.com/video/{media_id}",
        f"https://www.douyin.com:444/video/{media_id}",
        f"https://www.douyin.com:not-a-port/video/{media_id}",
    ):
        assert canonicalize_douyin_video_url(hostile) is None


def test_douyin_cookie_header_uses_profile_domain() -> None:
    normalized = normalize_cookies(DOUYIN_HEADER, cookie_domain_for_profile("douyin"))

    assert normalized is not None
    assert ".douyin.com\tTRUE" in normalized


def test_douyin_provider_reads_identity_from_passport_response(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(normalize_cookies(DOUYIN_HEADER, ".douyin.com") or "", encoding="utf-8")
    response = FakeResponse({
        "status_code": 0,
        "user": {
            "uid": "123456",
            "sec_uid": "MS4wLjABAAAAexample",
            "nickname": "Douyin user",
            "avatar_thumb": {"url_list": ["//p3.douyinpic.com/avatar.jpeg"]},
        },
    })
    http = Mock()
    http.get.return_value = response

    identity = DouyinProvider(http=http).verify(cookie_file)

    assert http.get.call_args.args[0] == "https://www.douyin.com/aweme/v1/web/user/profile/self/"
    assert http.get.call_args.kwargs["params"]["aid"] == "6383"
    assert identity.external_id == "123456"
    assert identity.display_name == "Douyin user"
    assert identity.avatar_url == "https://p3.douyinpic.com/avatar.jpeg"
    assert "custom_future_cookie" in {cookie.name for cookie in http.get.call_args.kwargs["cookies"]}


def test_douyin_provider_classifies_removed_identity_endpoint_as_unavailable(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(normalize_cookies(DOUYIN_HEADER, ".douyin.com") or "", encoding="utf-8")
    http = Mock()
    http.get.return_value = FakeResponse(status_code=404, text="<!doctype html><html></html>")

    with pytest.raises(DouyinProviderError) as exc:
        DouyinProvider(http=http).verify(cookie_file)

    assert exc.value.code == "provider_unavailable"
    assert exc.value.status_code == 503
    assert "HTTP 404" not in str(exc.value)


def test_douyin_provider_redacts_upstream_error_messages(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(normalize_cookies(DOUYIN_HEADER, ".douyin.com") or "", encoding="utf-8")
    for payload, expected_code in (
        ({"status_code": 461, "status_msg": "secret challenge payload"}, "provider_risk_control"),
        ({"status_code": 9999, "status_msg": "secret provider payload"}, "provider_response_invalid"),
    ):
        http = Mock()
        http.get.return_value = FakeResponse(payload)
        with pytest.raises(DouyinProviderError) as exc:
            DouyinProvider(http=http).verify(cookie_file)
        assert exc.value.code == expected_code
        assert "secret" not in str(exc.value).lower()
        assert "payload" not in str(exc.value).lower()


def test_douyin_provider_accepts_sid_guard_as_a_login_session(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(normalize_cookies("sid_guard=session-guard", ".douyin.com") or "", encoding="utf-8")

    DouyinProvider().validate_cookie_file(cookie_file)


def test_douyin_provider_rejects_login_cookie_from_another_domain(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(
        normalize_cookies('[{"name":"sessionid","value":"x","domain":".example.com"}]', ".douyin.com") or "",
        encoding="utf-8",
    )

    with pytest.raises(DouyinProviderError, match="signed-in web session"):
        DouyinProvider().validate_cookie_file(cookie_file)


def test_douyin_provider_classifies_explicit_login_expiry(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text(normalize_cookies(DOUYIN_HEADER, ".douyin.com") or "", encoding="utf-8")
    http = Mock()
    http.get.return_value = FakeResponse({"status_code": 100, "status_msg": "login expired"})

    with pytest.raises(DouyinProviderError) as exc:
        DouyinProvider(http=http).verify(cookie_file)

    assert exc.value.code == "account_login_invalid"
    assert exc.value.status_code == 424


def test_douyin_account_import_keeps_unknown_state_when_identity_check_is_blocked(tmp_path: Path) -> None:
    provider = FakeDouyinProvider(DouyinProviderError("provider_risk_control", "blocked", 503))
    service = AccountService(tmp_path, Storage(tmp_path / "server.db"), providers={"douyin": provider})

    account = service.create(AccountCreateRequest(
        platform="douyin",
        label="Douyin",
        cookie_content=DOUYIN_HEADER,
    ))

    assert account.platform == "douyin"
    assert account.state == "unknown"
    assert account.external_id is None
    assert account.last_error == "blocked"
    assert account.cookie_status.usable is True
    assert "custom_future_cookie" in cookie_names(service.resolve_cookie_file(account.id))


def test_douyin_cookie_replacement_clears_stale_identity_when_verification_is_blocked(tmp_path: Path) -> None:
    provider = FakeDouyinProvider(PlatformIdentity("123456", "First identity", "https://p3.douyinpic.com/avatar.jpeg"))
    service = AccountService(tmp_path, Storage(tmp_path / "server.db"), providers={"douyin": provider})
    account = service.create(AccountCreateRequest(
        platform="douyin",
        label="Douyin",
        cookie_content=DOUYIN_HEADER,
    ))
    provider.result = DouyinProviderError("provider_risk_control", "blocked", 503)

    replaced = service.update(account.id, AccountUpdateRequest(cookie_content=DOUYIN_HEADER.replace("session-value", "new-session")))

    assert replaced.state == "unknown"
    assert replaced.external_id is None
    assert replaced.display_name is None
    assert replaced.avatar_url is None
    assert replaced.last_error == "blocked"


def test_douyin_account_import_rejects_explicitly_invalid_login(tmp_path: Path) -> None:
    provider = FakeDouyinProvider(DouyinProviderError("account_login_invalid", "expired", 424))
    service = AccountService(tmp_path, Storage(tmp_path / "server.db"), providers={"douyin": provider})

    with pytest.raises(DouyinProviderError, match="expired"):
        service.create(AccountCreateRequest(
            platform="douyin",
            label="Douyin",
            cookie_content=DOUYIN_HEADER,
        ))

    assert service.list("douyin") == []


def test_douyin_analysis_uses_account_cookie_and_reports_target_probe(tmp_path: Path) -> None:
    cookie_file = tmp_path / "accounts" / "account" / "cookies.txt"
    cookie_file.parent.mkdir(parents=True)
    cookie_file.write_text(normalize_cookies(DOUYIN_HEADER, ".douyin.com") or "", encoding="utf-8")
    account = Mock(id="account", platform="douyin", label="Primary", state="unknown")
    account_service = Mock()
    account_service.storage.get_account.return_value = account
    account_service.resolve_cookie_file.return_value = cookie_file
    account_service.douyin_video_info.return_value = {
        "title": "Douyin video",
        "formats": [{"format_id": "download", "ext": "mp4", "vcodec": "h264", "acodec": "none", "url": "https://v.example/video.mp4"}],
    }

    proofs = DouyinDownloadProofStore()
    with patch("ytsage.server.services.analyzer.subprocess.run") as run:
        response = analyze(
            AnalyzeRequest(url="https://www.douyin.com/video/1234567890123456789", account_id="account"),
            config_dir=tmp_path,
            account_service=account_service,
            douyin_proofs=proofs,
        )

    run.assert_not_called()
    account_service.douyin_video_info.assert_called_once_with(
        "account", "https://www.douyin.com/video/1234567890123456789"
    )
    assert response.raw["account_identity_state"] == "unknown"
    assert response.raw["target_extraction_state"] == "valid"
    assert response.raw["resolved_single_video_url"] == "https://www.douyin.com/video/1234567890123456789"
    assert response.douyin_download_proof
    proofs.consume(response.douyin_download_proof, response.raw["resolved_single_video_url"], "account")


def test_douyin_analysis_uses_page_generated_video_detail(tmp_path: Path) -> None:
    cookie_file = tmp_path / "accounts" / "account" / "cookies.txt"
    cookie_file.parent.mkdir(parents=True)
    cookie_file.write_text(normalize_cookies(DOUYIN_HEADER, ".douyin.com") or "", encoding="utf-8")
    account = Mock(id="account", platform="douyin", label="Primary", state="unknown")
    account_service = Mock()
    account_service.storage.get_account.return_value = account
    account_service.resolve_cookie_file.return_value = cookie_file
    media_url = "https://v26-web.douyinvod.com/video?signature=opaque"
    account_service.douyin_video_info.return_value = {
        "id": "1234567890123456789",
        "title": "Browser video",
        "webpage_url": "https://www.douyin.com/video/1234567890123456789",
        "extractor": "DouyinBrowser",
        "channel": "Creator",
        "formats": [{
            "format_id": "browser-1-1080p-h264",
            "url": media_url,
            "ext": "mp4",
            "width": 1080,
            "height": 1920,
            "vcodec": "h264",
            "acodec": "aac",
        }],
    }
    proofs = DouyinDownloadProofStore()

    with patch("ytsage.server.services.analyzer.subprocess.run") as run:
        response = analyze(
            AnalyzeRequest(url="https://www.douyin.com/video/1234567890123456789", account_id="account"),
            config_dir=tmp_path,
            account_service=account_service,
            douyin_proofs=proofs,
        )

    run.assert_not_called()
    account_service.douyin_video_info.assert_called_once_with(
        "account", "https://www.douyin.com/video/1234567890123456789"
    )
    assert response.title == "Browser video"
    assert response.raw["target_extraction_state"] == "valid"
    assert response.formats[0].format_id == "browser-1-1080p-h264"
    assert media_url not in json.dumps(response.model_dump())
    media_info = proofs.consume(
        response.douyin_download_proof,
        "https://www.douyin.com/video/1234567890123456789",
        "account",
    )
    assert media_info is not None
    assert media_info["formats"][0]["url"] == media_url


def test_douyin_analysis_marks_metadata_without_formats_unavailable(tmp_path: Path) -> None:
    cookie_file = tmp_path / "accounts" / "account" / "cookies.txt"
    cookie_file.parent.mkdir(parents=True)
    cookie_file.write_text(normalize_cookies(DOUYIN_HEADER, ".douyin.com") or "", encoding="utf-8")
    account = Mock(id="account", platform="douyin", label="Primary", state="unknown")
    account_service = Mock()
    account_service.storage.get_account.return_value = account
    account_service.resolve_cookie_file.return_value = cookie_file
    account_service.douyin_video_info.return_value = {"title": "Metadata only", "formats": []}

    proofs = DouyinDownloadProofStore()
    with patch("ytsage.server.services.analyzer.subprocess.run") as run:
        response = analyze(
            AnalyzeRequest(url="https://www.douyin.com/video/1234567890123456789", account_id="account"),
            config_dir=tmp_path,
            account_service=account_service,
            douyin_proofs=proofs,
        )

    run.assert_not_called()
    assert response.raw["target_extraction_state"] == "unavailable"
    assert response.raw["warning_code"] == "metadata_without_formats"
    assert response.douyin_download_proof is None


def test_douyin_short_link_analysis_returns_resolved_video_url(tmp_path: Path) -> None:
    result = Mock(returncode=0, stderr="", stdout=json.dumps({
        "id": "1234567890123456789",
        "extractor_key": "Douyin",
        "webpage_url": "https://www.douyin.com/video/1234567890123456789",
        "formats": [{"format_id": "download", "ext": "mp4", "url": "https://v.example/video.mp4"}],
    }))

    with (
        patch("ytsage.server.services.analyzer.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.analyzer.subprocess.run", return_value=result),
    ):
        response = analyze(AnalyzeRequest(url="https://v.douyin.com/example/"), config_dir=tmp_path)

    assert response.raw["resolved_single_video_url"] == "https://www.douyin.com/video/1234567890123456789"


def test_douyin_analysis_rejects_playlists_without_an_account(tmp_path: Path) -> None:
    result = Mock(returncode=0, stderr="")
    result.stdout = json.dumps({
        "title": "Douyin collection",
        "entries": [{"id": "one", "url": "https://www.douyin.com/video/123"}],
    })

    with (
        patch("ytsage.server.services.analyzer.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.analyzer.subprocess.run", return_value=result),
        pytest.raises(HTTPException, match="single videos only"),
    ):
        analyze(
            AnalyzeRequest(url="https://www.douyin.com/user/example"),
            config_dir=tmp_path,
        )


@pytest.mark.anyio
async def test_douyin_task_rejects_unresolved_or_non_video_urls(tmp_path: Path) -> None:
    manager = TaskManager(Mock(config_dir=tmp_path), Storage(tmp_path / "server.db"))
    manager._publish = AsyncMock()

    for url in ("https://www.douyin.com/user/example", "https://v.douyin.com/example/"):
        with pytest.raises(ValueError, match="resolved single-video URL"):
            await manager.create_task(CreateTaskRequest(url=url))


@pytest.mark.anyio
async def test_douyin_task_rejects_missing_analysis_proof(tmp_path: Path) -> None:
    manager = TaskManager(Mock(config_dir=tmp_path), Storage(tmp_path / "server.db"))
    manager._publish = AsyncMock()

    with pytest.raises(DouyinProofError) as exc:
        await manager.create_task(CreateTaskRequest(url="https://www.douyin.com/video/1234567890123456789"))

    assert exc.value.code == "douyin_analysis_required"
    assert manager.storage.list_tasks() == []


@pytest.mark.anyio
async def test_douyin_task_accepts_bound_proof_once(tmp_path: Path) -> None:
    proofs = DouyinDownloadProofStore()
    manager = TaskManager(Mock(config_dir=tmp_path), Storage(tmp_path / "server.db"), douyin_proofs=proofs)
    manager._publish = AsyncMock()
    url = "https://www.douyin.com/video/1234567890123456789"
    proof = proofs.issue(url, None)

    task = await manager.create_task(CreateTaskRequest(url=url, douyin_download_proof=proof))

    assert task.status == "queued"
    assert task.url == url
    assert "douyin_download_proof" not in task.options
    with pytest.raises(DouyinProofError, match="already used"):
        await manager.create_task(CreateTaskRequest(url=url, douyin_download_proof=proof))


@pytest.mark.anyio
async def test_douyin_task_keeps_proof_media_only_in_memory(tmp_path: Path) -> None:
    proofs = DouyinDownloadProofStore()
    manager = TaskManager(Mock(config_dir=tmp_path), Storage(tmp_path / "server.db"), douyin_proofs=proofs)
    manager._publish = AsyncMock()
    url = "https://www.douyin.com/video/1234567890123456789"
    media_url = "https://v26-web.douyinvod.com/video?signature=opaque"
    proof = proofs.issue(url, None, {
        "id": "1234567890123456789",
        "title": "Video",
        "webpage_url": url,
        "formats": [{"format_id": "browser", "url": media_url}],
    })

    task = await manager.create_task(CreateTaskRequest(url=url, douyin_download_proof=proof))

    assert manager._douyin_media_info[task.id]["formats"][0]["url"] == media_url
    assert media_url not in json.dumps(task.model_dump())
    assert "douyin_download_proof" not in task.options


@pytest.mark.anyio
async def test_douyin_proof_survives_validation_failure_before_consumption(tmp_path: Path) -> None:
    proofs = DouyinDownloadProofStore()
    manager = TaskManager(Mock(config_dir=tmp_path), Storage(tmp_path / "server.db"), douyin_proofs=proofs)
    manager._publish = AsyncMock()
    url = "https://www.douyin.com/video/1234567890123456789"
    proof = proofs.issue(url, None)

    with pytest.raises(ValueError, match="Custom cookie file paths"):
        await manager.create_task(CreateTaskRequest(
            url=url,
            cookie_file=str(tmp_path / "not-allowed.txt"),
            douyin_download_proof=proof,
        ))

    task = await manager.create_task(CreateTaskRequest(url=url, douyin_download_proof=proof))
    assert task.status == "queued"
    with pytest.raises(DouyinProofError, match="already used"):
        await manager.create_task(CreateTaskRequest(url=url, douyin_download_proof=proof))


@pytest.mark.anyio
async def test_douyin_proof_rejects_url_account_expiry_and_restart(tmp_path: Path) -> None:
    now = [10.0]
    proofs = DouyinDownloadProofStore(ttl_seconds=5, clock=lambda: now[0])
    account_service = Mock()
    account_service.resolve_cookie_file.return_value = tmp_path / "cookies.txt"
    manager = TaskManager(
        Mock(config_dir=tmp_path),
        Storage(tmp_path / "server.db"),
        account_service=account_service,
        douyin_proofs=proofs,
    )
    manager._publish = AsyncMock()
    first_url = "https://www.douyin.com/video/1234567890123456789"
    second_url = "https://www.douyin.com/video/9876543210987654321"

    with pytest.raises(DouyinProofError) as mismatch:
        await manager.create_task(CreateTaskRequest(
            url=second_url,
            account_id="account",
            douyin_download_proof=proofs.issue(first_url, "account"),
        ))
    assert mismatch.value.code == "douyin_proof_mismatch"

    with pytest.raises(DouyinProofError) as account_mismatch:
        await manager.create_task(CreateTaskRequest(
            url=first_url,
            account_id="other-account",
            douyin_download_proof=proofs.issue(first_url, "account"),
        ))
    assert account_mismatch.value.code == "douyin_proof_mismatch"

    expired = proofs.issue(first_url, None)
    now[0] = 16.0
    with pytest.raises(DouyinProofError) as expired_error:
        await manager.create_task(CreateTaskRequest(url=first_url, douyin_download_proof=expired))
    assert expired_error.value.code == "douyin_proof_expired"

    restarted_store_manager = TaskManager(Mock(config_dir=tmp_path), Storage(tmp_path / "restart.db"))
    with pytest.raises(DouyinProofError) as restarted_error:
        await restarted_store_manager.create_task(CreateTaskRequest(
            url=first_url,
            douyin_download_proof=proofs.issue(first_url, None),
        ))
    assert restarted_error.value.code == "douyin_proof_invalid"


def test_douyin_analysis_failures_are_stable_and_sanitized(tmp_path: Path) -> None:
    cases = [
        ("ERROR: fresh cookies needed --cookies C:/secret/account.txt", "fresh_cookies_required", 424),
        ("ERROR: HTTP Error 403: CAPTCHA challenge Authorization: secret", "provider_risk_control", 503),
        ("ERROR: extractor crashed --header Cookie: secret", "provider_unavailable", 503),
    ]
    for output, code, status_code in cases:
        result = Mock(returncode=1, stderr=output, stdout="")
        with (
            patch("ytsage.server.services.analyzer.ytdlp_base_command", return_value=["yt-dlp"]),
            patch("ytsage.server.services.analyzer.subprocess.run", return_value=result),
            pytest.raises(HTTPException) as exc,
        ):
            analyze(AnalyzeRequest(url="https://www.douyin.com/video/1234567890123456789"), config_dir=tmp_path)
        assert exc.value.status_code == status_code
        assert exc.value.detail["code"] == code
        assert "secret" not in json.dumps(exc.value.detail).lower()
        assert "cookies" not in json.dumps(exc.value.detail).lower() or code == "fresh_cookies_required"


def test_douyin_invalid_provider_response_is_sanitized(tmp_path: Path) -> None:
    result = Mock(returncode=0, stderr="", stdout="C:/secret/cookies.txt is not JSON")
    with (
        patch("ytsage.server.services.analyzer.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.analyzer.subprocess.run", return_value=result),
        pytest.raises(HTTPException) as exc,
    ):
        analyze(AnalyzeRequest(url="https://www.douyin.com/video/1234567890123456789"), config_dir=tmp_path)

    assert exc.value.status_code == 503
    assert exc.value.detail == {"code": "provider_unavailable", "message": "Douyin analysis is currently unavailable."}


def test_douyin_analysis_timeout_is_sanitized(tmp_path: Path) -> None:
    with (
        patch("ytsage.server.services.analyzer.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.analyzer.subprocess.run", side_effect=subprocess.TimeoutExpired(["yt-dlp", "--cookies", "secret"], 60)),
        pytest.raises(HTTPException) as exc,
    ):
        analyze(AnalyzeRequest(url="https://www.douyin.com/video/1234567890123456789"), config_dir=tmp_path)

    assert exc.value.status_code == 504
    assert exc.value.detail == {"code": "provider_timeout", "message": "Douyin analysis timed out. Try again."}


@pytest.mark.anyio
async def test_douyin_api_analysis_proof_is_required_and_queues_only_bound_video(tmp_path: Path) -> None:
    proofs = DouyinDownloadProofStore()
    storage = Storage(tmp_path / "server.db")
    config = Mock(config_dir=tmp_path)
    account_service = Mock()
    manager = TaskManager(config, storage, account_service, proofs)
    manager._publish = AsyncMock()
    analysis_router = create_analysis_router(config, account_service, lambda: None, proofs)
    tasks_router = create_tasks_router(config, storage, manager, lambda: None)
    analyze_endpoint = next(route.endpoint for route in analysis_router.routes if route.path == "/api/analyze")
    create_endpoint = next(route.endpoint for route in tasks_router.routes if route.path == "/api/tasks" and "POST" in route.methods)
    url = "https://www.douyin.com/video/1234567890123456789"
    result = Mock(returncode=0, stderr="", stdout=json.dumps({
        "id": "1234567890123456789",
        "extractor_key": "Douyin",
        "formats": [{"format_id": "download", "url": "https://v.example/video.mp4"}],
    }))

    with pytest.raises(HTTPException) as missing:
        await create_endpoint(CreateTaskRequest(url=url))
    with pytest.raises(HTTPException) as forged:
        await create_endpoint(CreateTaskRequest(url=url, douyin_download_proof="forged-proof-value-12345"))
    with (
        patch("ytsage.server.services.analyzer.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.analyzer.subprocess.run", return_value=result),
    ):
        analyzed = analyze_endpoint(AnalyzeRequest(url=url))
    created = await create_endpoint(CreateTaskRequest(
        url=url,
        douyin_download_proof=analyzed.douyin_download_proof,
    ))

    assert missing.value.status_code == 424
    assert missing.value.detail["code"] == "douyin_analysis_required"
    assert forged.value.status_code == 424
    assert forged.value.detail["code"] == "douyin_proof_invalid"
    assert analyzed.douyin_download_proof
    assert created.status == "queued"
    assert len(storage.list_tasks()) == 1


@pytest.mark.anyio
async def test_douyin_history_redownload_requires_new_analysis(tmp_path: Path) -> None:
    proofs = DouyinDownloadProofStore()
    storage = Storage(tmp_path / "server.db")
    config = Mock(config_dir=tmp_path)
    manager = TaskManager(config, storage, douyin_proofs=proofs)
    manager._publish = AsyncMock()
    url = "https://www.douyin.com/video/1234567890123456789"
    original = storage.create_task("original", CreateTaskRequest(url=url))
    storage.add_history(HistoryEntry(
        id="history",
        task_id=original.id,
        url=url,
        downloaded_at="2026-01-01T00:00:00+00:00",
    ))
    router = create_tasks_router(config, storage, manager, lambda: None)
    redownload_endpoint = next(
        route.endpoint
        for route in router.routes
        if route.path == "/api/history/{history_id}/redownload" and "POST" in route.methods
    )

    with pytest.raises(HTTPException) as exc:
        await redownload_endpoint("history")

    assert exc.value.status_code == 424
    assert exc.value.detail == {
        "code": "douyin_analysis_required",
        "message": "Analyze this Douyin video before creating a download task.",
    }
    assert [task.id for task in storage.list_tasks()] == ["original"]


@pytest.mark.anyio
async def test_douyin_resume_and_recovered_tasks_require_new_analysis(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "server.db")
    url = "https://www.douyin.com/video/1234567890123456789"
    task = storage.create_task("interrupted", CreateTaskRequest(url=url))
    storage.update_task(task.id, status="failed")
    manager = TaskManager(Mock(config_dir=tmp_path), storage)
    manager._publish = AsyncMock()
    manager._execute_download = AsyncMock()

    with pytest.raises(DouyinProofError) as exc:
        await manager.resume_task(task.id)
    assert exc.value.code == "douyin_analysis_required"

    recovered = storage.update_task(task.id, status="queued", error=None, finished_at=None)
    await manager._run_task(recovered)

    failed = storage.get_task(task.id)
    assert failed.status == "failed"
    assert "Analyze this Douyin video again" in (failed.error or "")
    manager._execute_download.assert_not_awaited()
    manager._publish.assert_awaited_once()

    router = create_tasks_router(Mock(config_dir=tmp_path), storage, manager, lambda: None)
    resume_endpoint = next(
        route.endpoint
        for route in router.routes
        if route.path == "/api/tasks/{task_id}/resume" and "POST" in route.methods
    )
    with pytest.raises(HTTPException) as api_error:
        await resume_endpoint(task.id)
    assert api_error.value.status_code == 424
    assert api_error.value.detail["code"] == "douyin_analysis_required"


@pytest.mark.anyio
async def test_douyin_restart_requires_new_analysis(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "server.db")
    url = "https://www.douyin.com/video/1234567890123456789"
    original = storage.create_task("original", CreateTaskRequest(url=url))
    storage.update_task(original.id, status="failed")
    manager = TaskManager(Mock(config_dir=tmp_path), storage)
    manager._publish = AsyncMock()

    with pytest.raises(DouyinProofError) as exc:
        await manager.restart_task(original.id)

    assert exc.value.code == "douyin_analysis_required"
    assert [task.id for task in storage.list_tasks()] == ["original"]


@pytest.mark.anyio
async def test_douyin_restart_api_returns_stable_analysis_required_error(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "server.db")
    url = "https://www.douyin.com/video/1234567890123456789"
    original = storage.create_task("original", CreateTaskRequest(url=url))
    storage.update_task(original.id, status="failed")
    manager = TaskManager(Mock(config_dir=tmp_path), storage)
    manager._publish = AsyncMock()
    router = create_tasks_router(Mock(config_dir=tmp_path), storage, manager, lambda: None)
    restart_endpoint = next(
        route.endpoint
        for route in router.routes
        if route.path == "/api/tasks/{task_id}/restart" and "POST" in route.methods
    )

    with pytest.raises(HTTPException) as exc:
        await restart_endpoint(original.id)

    assert exc.value.status_code == 424
    assert exc.value.detail["code"] == "douyin_analysis_required"


@pytest.mark.anyio
async def test_douyin_task_rejects_playlist_downloads(tmp_path: Path) -> None:
    manager = TaskManager(Mock(config_dir=tmp_path), Storage(tmp_path / "server.db"))
    manager._publish = AsyncMock()

    with pytest.raises(ValueError, match="single videos only"):
        await manager.create_task(CreateTaskRequest(
            url="https://www.douyin.com/video/1234567890123456789",
            playlist_entries=[PlaylistEntry(index=1, id="one", url="https://www.douyin.com/video/1234567890123456789")],
        ))
