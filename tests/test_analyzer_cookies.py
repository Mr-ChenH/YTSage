import json
from pathlib import Path
from unittest.mock import Mock, patch

import requests

from ytsage.server.analyzers.bilibili import validate_cookie_login
from ytsage.server.models import AnalyzeRequest
from ytsage.server.services.analyzer import analyze
from ytsage.server.services.cookies import cookie_profile_statuses


def _result() -> Mock:
    result = Mock(returncode=0, stderr="")
    result.stdout = json.dumps({
        "title": "Video",
        "formats": [{"format_id": "18", "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a"}],
    })
    return result


def _write_cookie(path: Path, expiry: int, authenticated: bool = False) -> None:
    rows = [f".youtube.com\tTRUE\t/\tTRUE\t{expiry}\tSID\tvalue"]
    if authenticated:
        rows.extend([
            f".youtube.com\tTRUE\t/\tTRUE\t{expiry}\tLOGIN_INFO\tlogin",
            f".youtube.com\tTRUE\t/\tTRUE\t{expiry}\tSAPISID\tsapisid",
        ])
    path.write_text("# Netscape HTTP Cookie File\n" + "\n".join(rows) + "\n", encoding="utf-8")


def test_analyze_reports_cookie_verified_when_it_was_used(tmp_path: Path) -> None:
    cookie_path = tmp_path / "cookies-youtube.txt"
    _write_cookie(cookie_path, 4_000_000_000, authenticated=True)

    with (
        patch("ytsage.server.services.analyzer.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.analyzer.subprocess.run", return_value=_result()) as run,
    ):
        response = analyze(AnalyzeRequest(url="https://www.youtube.com/watch?v=video"), config_dir=tmp_path)

    command = run.call_args.args[0]
    assert command[command.index("--cookies") + 1] == str(cookie_path)
    assert response.raw["cookie_profile"] == "youtube"
    assert response.raw["cookie_expiry_status"] == "valid"
    assert response.raw["cookie_login_status"] == "valid"


def test_analyze_reports_incomplete_youtube_login_cookie_as_invalid(tmp_path: Path) -> None:
    _write_cookie(tmp_path / "cookies-youtube.txt", 4_000_000_000)

    with (
        patch("ytsage.server.services.analyzer.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.analyzer.subprocess.run", return_value=_result()),
    ):
        response = analyze(AnalyzeRequest(url="https://www.youtube.com/watch?v=video"), config_dir=tmp_path)

    assert response.raw["cookie_expiry_status"] == "valid"
    assert response.raw["cookie_login_status"] == "invalid"
    assert cookie_profile_statuses(tmp_path)["youtube"].login_state == "invalid"


def test_bilibili_cookie_login_uses_online_account_status(tmp_path: Path) -> None:
    cookie_path = tmp_path / "cookies-bilibili.txt"
    cookie_path.write_text("# Netscape HTTP Cookie File\n.bilibili.com\tTRUE\t/\tTRUE\t0\tSESSDATA\tvalue\n", encoding="utf-8")
    response = Mock(status_code=200, content=b'{"data":{"isLogin":true}}')
    http = Mock()
    http.get.return_value = response

    assert validate_cookie_login(cookie_path, http=http) == "valid"

    response.content = b'{"data":{"isLogin":false}}'
    assert validate_cookie_login(cookie_path, http=http) == "invalid"

    http.get.side_effect = requests.RequestException("offline")
    assert validate_cookie_login(cookie_path, http=http) == "unknown"


def test_analyze_reports_expired_cookie_without_passing_it_to_ytdlp(tmp_path: Path) -> None:
    _write_cookie(tmp_path / "cookies-youtube.txt", 1)

    with (
        patch("ytsage.server.services.analyzer.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.analyzer.subprocess.run", return_value=_result()) as run,
    ):
        response = analyze(AnalyzeRequest(url="https://www.youtube.com/watch?v=video"), config_dir=tmp_path)

    command = run.call_args.args[0]
    assert "--cookies" not in command
    assert response.raw["cookie_profile"] == "youtube"
    assert response.raw["cookie_expiry_status"] == "expired"
    assert response.raw["cookie_login_status"] == "invalid"
