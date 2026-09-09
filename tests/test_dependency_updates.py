from unittest.mock import Mock, patch

from ytsage.server.services.dependencies import CommandInfo
from ytsage.server.services.dependency_updates import DependencyUpdateManager, _display_ffmpeg_version, _is_newer


def test_version_comparison_handles_ytdlp_calendar_versions() -> None:
    assert _is_newer("2026.09.09", "2026.08.14")
    assert not _is_newer("2026.08.14", "2026.08.14")
    assert _is_newer("1.0", None)


def test_ffmpeg_version_is_shortened_for_display() -> None:
    assert _display_ffmpeg_version("ffmpeg version 8.1.2-static Copyright (c) 2000-2026") == "8.1.2-static"
    assert _display_ffmpeg_version("7.1") == "7.1"


def test_check_reports_updates_and_system_managed_ffmpeg() -> None:
    latest = Mock(side_effect=lambda package: {"yt-dlp": "2026.09.09"}[package])
    manager = DependencyUpdateManager(latest_version=latest)
    with (
        patch("ytsage.server.services.dependency_updates.get_ytdlp_info", return_value=CommandInfo(["yt-dlp"], "2026.08.14", "python-module")),
        patch("ytsage.server.services.dependency_updates.get_ffmpeg_info", return_value=CommandInfo(["ffmpeg"], "7.1", "cli")),
    ):
        status = manager.check()

    ytdlp, ffmpeg = status["dependencies"]
    assert ytdlp["update_available"] is True
    assert ytdlp["latest_version"] == "2026.09.09"
    assert ffmpeg["managed"] is False
    assert ffmpeg["latest_version"] is None
    assert status["phase"] == "ready"
    assert status["running"] is False


def test_update_skips_current_and_system_managed_dependencies() -> None:
    manager = DependencyUpdateManager(latest_version=lambda _package: "2026.08.14")
    manager._run_pip = Mock()  # type: ignore[method-assign]
    with (
        patch("ytsage.server.services.dependency_updates.get_ytdlp_info", return_value=CommandInfo(["yt-dlp"], "2026.08.14", "python-module")),
        patch("ytsage.server.services.dependency_updates.get_ffmpeg_info", return_value=CommandInfo(["ffmpeg"], "7.1", "cli")),
        patch("ytsage.server.services.dependency_updates.clear_dependency_cache"),
    ):
        manager._update()

    status = manager.status()
    manager._run_pip.assert_not_called()  # type: ignore[attr-defined]
    assert status["phase"] == "completed"
    assert any("already current" in line for line in status["logs"])
    assert any("system or container" in line for line in status["logs"])
