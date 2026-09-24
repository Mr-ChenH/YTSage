from pathlib import Path

from ytsage.server.api.system import create_system_router
from ytsage.server.config import ServerConfig
from ytsage.server.models import CookieSaveRequest
from ytsage.server.services.cookies import (
    clear_cookie_login_status,
    cookie_file_for_url,
    cookie_profile_status,
    cookie_profile_statuses,
    save_cookie_login_status,
)


def _write_cookie(path: Path, expiry: int, name: str = "session") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        f".example.com\tTRUE\t/\tTRUE\t{expiry}\t{name}\tvalue\n",
        encoding="utf-8",
    )


def test_cookie_status_reports_valid_cookie(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    _write_cookie(path, 2_000_000_000)

    status = cookie_profile_status(path, now=1_900_000_000)

    assert status.state == "valid"
    assert status.usable is True
    assert status.valid_count == 1
    assert status.earliest_expiry == 2_000_000_000


def test_cookie_status_reports_expiring_cookie(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    _write_cookie(path, 1_900_000_000 + 60)

    status = cookie_profile_status(path, now=1_900_000_000)

    assert status.state == "expiring"
    assert status.usable is True


def test_cookie_status_reports_expired_cookie(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    _write_cookie(path, 1_800_000_000)

    status = cookie_profile_status(path, now=1_900_000_000)

    assert status.state == "expired"
    assert status.usable is False
    assert status.expired_count == 1


def test_cookie_status_treats_session_cookie_as_usable(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    _write_cookie(path, 0)

    status = cookie_profile_status(path, now=1_900_000_000)

    assert status.state == "session"
    assert status.usable is True
    assert status.session_count == 1


def test_cookie_status_reports_invalid_file(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text("# no cookie rows\ninvalid row\n", encoding="utf-8")

    status = cookie_profile_status(path, now=1_900_000_000)

    assert status.state == "invalid"
    assert status.usable is False


def test_cookie_status_reads_httponly_cookie_rows(tmp_path: Path) -> None:
    path = tmp_path / "cookies.txt"
    path.write_text(
        "# Netscape HTTP Cookie File\n"
        "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n",
        encoding="utf-8",
    )

    status = cookie_profile_status(path, now=1_900_000_000)

    assert status.state == "session"
    assert status.session_count == 1
    assert status.usable is True



def test_cookie_statuses_include_and_clear_latest_login_check(tmp_path: Path) -> None:
    _write_cookie(tmp_path / "cookies-youtube.txt", 2_000_000_000)
    save_cookie_login_status(tmp_path, "youtube", "invalid")

    status = cookie_profile_statuses(tmp_path)["youtube"]

    assert status.login_state == "invalid"
    assert status.login_checked_at is not None

    clear_cookie_login_status(tmp_path, "youtube")
    status = cookie_profile_statuses(tmp_path)["youtube"]
    assert status.login_state is None
    assert status.login_checked_at is None


def test_douyin_settings_accept_cookie_header_with_profile_domain(tmp_path: Path) -> None:
    config = ServerConfig(
        host="127.0.0.1",
        port=8080,
        config_dir=tmp_path / "config",
        download_dir=tmp_path / "downloads",
        queue_concurrency=1,
        auth_token=None,
        static_dir=tmp_path / "static",
    )
    config.config_dir.mkdir()
    config.download_dir.mkdir()
    router = create_system_router(config, lambda: None)
    endpoint = next(route.endpoint for route in router.routes if route.path == "/api/settings/cookies")

    response = endpoint(CookieSaveRequest(
        profile="douyin",
        content="sessionid=session; ttwid=device",
    ))

    assert response.cookies_configured is True
    content = (config.config_dir / "cookies-douyin.txt").read_text(encoding="utf-8")
    assert ".douyin.com\tTRUE" in content
    assert "\tsessionid\tsession" in content


def test_expired_site_cookie_falls_back_to_usable_default(tmp_path: Path) -> None:
    _write_cookie(tmp_path / "cookies-youtube.txt", 1)
    _write_cookie(tmp_path / "cookies.txt", 0)

    selected = cookie_file_for_url(tmp_path, "https://www.youtube.com/watch?v=video")

    assert selected == tmp_path / "cookies.txt"
