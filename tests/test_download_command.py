from pathlib import Path
from unittest.mock import Mock, patch

from ytsage.server.models import CreateTaskRequest, PlaylistEntry, TaskProgress
from ytsage.server.services.analyzer import _bilibili_collection_from_api
from ytsage.server.services.dependencies import ytdlp_base_command
from ytsage.server.services.download_service import build_download_command, parse_progress_line
from ytsage.server.services.task_manager import _playlist_item_filename_template


def test_progress_error_does_not_finalize_playlist_failure() -> None:
    current = TaskProgress(playlist_current_index=3)

    progress = parse_progress_line("ERROR: transient fragment request failed", current)

    assert progress.status_text == "ERROR: transient fragment request failed"
    assert progress.playlist_failed_indexes == []
    assert progress.playlist_failures == {}


def test_progress_line_extracts_download_speed_and_eta() -> None:
    progress = parse_progress_line("[download]   5.8% of   44.96MiB at  119.52KiB/s ETA 02:26")

    assert progress.percent == 5.8
    assert progress.speed == "119.52KiB/s"
    assert progress.eta == "02:26"


def test_progress_line_handles_mib_speed() -> None:
    progress = parse_progress_line("[download]  50.0% of  100.00MiB at    2.54MiB/s ETA 00:19")

    assert progress.speed == "2.54MiB/s"
    assert progress.eta == "00:19"


def test_progress_line_keeps_last_speed_when_current_line_has_no_speed() -> None:
    current = TaskProgress(speed="800.00KiB/s", eta="00:10")

    progress = parse_progress_line("[download] 100% of 17.15MiB in 00:00:04", current)

    assert progress.percent == 100.0
    assert progress.speed == "800.00KiB/s"
    assert progress.eta == "00:10"


def test_playlist_item_filename_template_resolves_playlist_fields() -> None:
    template = "%(playlist_title)s/%(playlist_index)02d-%(title)s.%(ext)s"

    assert _playlist_item_filename_template(template, "Course", 7) == "Course/07-%(title)s.%(ext)s"


def test_single_video_download_uses_title_directory() -> None:
    request = CreateTaskRequest(
        url="https://example.com/video",
        filename_template="%(title)s_%(resolution)s_[%(id)s].%(ext)s",
    )

    with (
        patch("ytsage.server.services.download_service.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.download_service.ffmpeg_location_arg", return_value=None),
    ):
        command = build_download_command(request, Path("/downloads"))

    assert command[command.index("-o") + 1] == "%(title)s/%(title)s_%(resolution)s_[%(id)s].%(ext)s"


def test_single_video_title_directory_is_not_duplicated() -> None:
    request = CreateTaskRequest(
        url="https://example.com/video",
        filename_template="%(title)s/%(title)s.%(ext)s",
    )

    with (
        patch("ytsage.server.services.download_service.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.download_service.ffmpeg_location_arg", return_value=None),
    ):
        command = build_download_command(request, Path("/downloads"))

    assert command[command.index("-o") + 1] == "%(title)s/%(title)s.%(ext)s"


def test_playlist_download_keeps_playlist_directory_template() -> None:
    request = CreateTaskRequest(
        url="https://example.com/playlist",
        playlist_entries=[PlaylistEntry(index=1, url="https://example.com/video/1")],
        filename_template="%(playlist_title)s/%(playlist_index)02d-%(title)s.%(ext)s",
    )

    with (
        patch("ytsage.server.services.download_service.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.download_service.ffmpeg_location_arg", return_value=None),
    ):
        command = build_download_command(request, Path("/downloads"))

    assert command[command.index("-o") + 1] == "%(playlist_title)s/%(playlist_index)02d-%(title)s.%(ext)s"


def test_split_playlist_item_does_not_add_title_directory() -> None:
    request = CreateTaskRequest(
        url="https://example.com/video/1",
        filename_template="Course/01-%(title)s.%(ext)s",
    )

    with (
        patch("ytsage.server.services.download_service.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.download_service.ffmpeg_location_arg", return_value=None),
    ):
        command = build_download_command(request, Path("/downloads"), single_item_directory=False)

    assert command[command.index("-o") + 1] == "Course/01-%(title)s.%(ext)s"


def test_playlist_format_has_audio_and_fallbacks() -> None:
    request = CreateTaskRequest(
        url="https://www.bilibili.com/video/BVexample",
        format_id="80",
        playlist_items="1-3",
    )

    with (
        patch("ytsage.server.services.download_service.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.download_service.ffmpeg_location_arg", return_value=None),
    ):
        command = build_download_command(request, Path("/downloads"))

    selector = command[command.index("-f") + 1]
    assert selector == "80+bestaudio/80/bestvideo*+bestaudio/best"
    assert "--ignore-errors" in command


def test_full_playlist_format_has_fallbacks_without_playlist_items() -> None:
    request = CreateTaskRequest(
        url="https://www.bilibili.com/video/BVexample",
        format_id="100026",
        playlist_entries=[PlaylistEntry(index=1, url="https://www.bilibili.com/video/BVexample/?p=1")],
    )

    with (
        patch("ytsage.server.services.download_service.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.download_service.ffmpeg_location_arg", return_value=None),
    ):
        command = build_download_command(request, Path("/downloads"))

    assert command[command.index("-f") + 1] == "100026+bestaudio/100026/bestvideo*+bestaudio/best"


def test_bilibili_multi_page_metadata_uses_page_titles() -> None:
    response = Mock(status_code=200)
    response.content = b'{"data":{"title":"Course","pic":"cover.jpg","owner":{"name":"Teacher"},"pages":[{"page":1,"cid":101,"part":"Introduction","duration":120},{"page":2,"cid":102,"part":"Advanced topic","duration":180}]}}'

    with patch("ytsage.server.services.analyzer.requests.get", return_value=response):
        title, entries = _bilibili_collection_from_api("https://www.bilibili.com/video/BV1example/")

    assert title == "Course"
    assert [entry.title for entry in entries] == ["Introduction", "Advanced topic"]
    assert [entry.id for entry in entries] == ["BV1example_p1", "BV1example_p2"]
    assert entries[1].url == "https://www.bilibili.com/video/BV1example/?p=2"
    assert entries[0].channel == "Teacher"


def test_youtube_download_uses_ejs_and_http_chunks() -> None:
    request = CreateTaskRequest(
        url="https://www.youtube.com/playlist?list=PLexample",
        format_id="399",
        playlist_entries=[PlaylistEntry(index=1)],
    )

    with (
        patch("ytsage.server.services.download_service.ytdlp_base_command", return_value=["yt-dlp", "--js-runtimes", "deno"]),
        patch("ytsage.server.services.download_service.ffmpeg_location_arg", return_value=None),
    ):
        command = build_download_command(request, Path("/downloads"))

    assert command[command.index("--remote-components") + 1] == "ejs:github"
    assert command[command.index("--http-chunk-size") + 1] == "2M"
    assert command[command.index("--socket-timeout") + 1] == "45"
    assert command[command.index("--retries") + 1] == "5"
    assert command[command.index("--retry-sleep") + 1] == "http:exp=1:8"


def test_youtube_android_fallback_uses_combined_format() -> None:
    request = CreateTaskRequest(url="https://www.youtube.com/watch?v=example", format_id="18")

    with (
        patch("ytsage.server.services.download_service.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.download_service.ffmpeg_location_arg", return_value=None),
    ):
        command = build_download_command(request, Path("/downloads"))

    assert command[command.index("-f") + 1] == "18"
    assert command[command.index("--extractor-args") + 1] == "youtube:player_client=android"


def test_non_youtube_download_does_not_enable_youtube_workarounds() -> None:
    request = CreateTaskRequest(url="https://www.bilibili.com/video/BVexample")

    with (
        patch("ytsage.server.services.download_service.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.download_service.ffmpeg_location_arg", return_value=None),
    ):
        command = build_download_command(request, Path("/downloads"))

    assert "--remote-components" not in command
    assert "--http-chunk-size" not in command


def test_single_video_format_adds_audio_and_fallbacks() -> None:
    request = CreateTaskRequest(url="https://example.com/video", format_id="137")

    with (
        patch("ytsage.server.services.download_service.ytdlp_base_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.download_service.ffmpeg_location_arg", return_value=None),
    ):
        command = build_download_command(request, Path("/downloads"))

    assert command[command.index("-f") + 1] == "137+bestaudio/137/bestvideo*+bestaudio/best"


def test_deno_runtime_is_passed_to_ytdlp() -> None:
    with (
        patch("ytsage.server.services.dependencies.ytdlp_command", return_value=["yt-dlp"]),
        patch("ytsage.server.services.dependencies.shutil.which", return_value="/usr/bin/deno"),
    ):
        assert ytdlp_base_command() == ["yt-dlp", "--js-runtimes", "deno:/usr/bin/deno"]
