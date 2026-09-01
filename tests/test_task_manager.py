from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from ytsage.server.models import CreateTaskRequest, PlaylistEntry, TaskProgress, TaskResponse
from ytsage.server.services.task_manager import TaskManager


def _task(entries: list[PlaylistEntry]) -> TaskResponse:
    request = CreateTaskRequest(
        url="https://www.youtube.com/playlist?list=playlist",
        playlist_title="Course",
        playlist_entries=entries,
        filename_template="%(playlist_title)s/%(playlist_index)02d-%(title)s.%(ext)s",
    )
    return TaskResponse(
        id="task",
        url=request.url,
        mode="video",
        status="queued",
        options=request.model_dump(),
        progress=TaskProgress(),
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    )


@pytest.mark.anyio
async def test_single_youtube_video_retries_403_with_android_format() -> None:
    task = _task([])
    request = CreateTaskRequest(
        url="https://www.youtube.com/watch?v=video",
        format_id="399",
        cookie_file="cookies.txt",
    )
    manager = TaskManager(Mock(), Mock())
    manager._execute_download = AsyncMock(
        side_effect=[
            (["ERROR: unable to download video data: HTTP Error 403: Forbidden"], 1, None, TaskProgress()),
            (["downloaded"], 0, "/downloads/video.mp4", TaskProgress()),
        ]
    )

    output, return_code, output_path, progress = await manager._execute_with_youtube_fallback(
        task, request, TaskProgress()
    )

    assert return_code == 0
    assert output_path == "/downloads/video.mp4"
    assert "HTTP Error 403" in output[0]
    fallback_request = manager._execute_download.await_args_list[1].args[1]
    assert fallback_request.format_id == "18"
    assert fallback_request.cookie_file is None
    assert manager._execute_download.await_args_list[1].kwargs["use_cookies"] is False
    assert progress.status_text == "Downloaded at 360p after YouTube rejected the selected format"


@pytest.mark.anyio
async def test_successful_download_with_error_log_does_not_trigger_fallback() -> None:
    task = _task([])
    request = CreateTaskRequest(url="https://www.youtube.com/watch?v=video", format_id="399")
    manager = TaskManager(Mock(), Mock())
    manager._execute_download = AsyncMock(
        return_value=(["ERROR: transient HTTP Error 403: Forbidden", "[download] 100%"], 0, "/downloads/video.mp4", TaskProgress())
    )

    _, return_code, output_path, _ = await manager._execute_with_youtube_fallback(task, request, TaskProgress())

    assert return_code == 0
    assert output_path == "/downloads/video.mp4"
    assert manager._execute_download.await_count == 1


@pytest.mark.anyio
async def test_playlist_item_with_transient_error_and_zero_exit_is_completed() -> None:
    entry = PlaylistEntry(index=2, url="https://www.youtube.com/watch?v=video-2")
    task = _task([entry])
    stored_task = task.model_copy(update={"status": "running"})
    manager = TaskManager(Mock(), Mock())

    def update_task(_task_id: str, **fields: object) -> TaskResponse:
        nonlocal stored_task
        stored_task = stored_task.model_copy(update=fields)
        return stored_task

    manager.storage.get_task.side_effect = lambda _task_id: stored_task
    manager.storage.update_task.side_effect = update_task
    manager._publish = AsyncMock()
    manager._execute_with_youtube_fallback = AsyncMock(
        return_value=(["ERROR: transient fragment failure", "[download] 100%"], 0, "/downloads/video-2.mp4", TaskProgress(status_text="ERROR: transient fragment failure"))
    )

    _, return_code, _, progress = await manager._execute_playlist_entries(
        task, CreateTaskRequest(**task.options), [entry], TaskProgress()
    )

    assert return_code == 0
    assert progress.playlist_failed_indexes == []
    assert progress.playlist_completed_indexes == [2]
    assert progress.status_text == "Downloaded playlist item 1 of 1"


@pytest.mark.anyio
async def test_single_selected_playlist_entry_uses_entry_url() -> None:
    entry = PlaylistEntry(index=4, url="https://www.youtube.com/watch?v=video-4")
    task = _task([entry])
    manager = TaskManager(Mock(), Mock())
    manager.storage.get_task.return_value = task.model_copy(update={"status": "running"})
    manager.storage.update_task.side_effect = lambda *_args, **fields: task.model_copy(update=fields)
    manager._publish = AsyncMock()
    manager._execute_download = AsyncMock(return_value=([], 0, "/downloads/video.mp4", TaskProgress()))

    await manager._run_task(task)

    request = manager._execute_download.await_args.args[1]
    assert request.url == entry.url
    assert request.playlist_items is None
    assert request.playlist_entries == []
    assert request.filename_template == "Course/04-%(title)s.%(ext)s"


@pytest.mark.anyio
async def test_playlist_retry_keeps_later_items_pending_after_interruption() -> None:
    entries = [
        PlaylistEntry(index=index, url=f"https://www.youtube.com/watch?v=video-{index}")
        for index in range(1, 6)
    ]
    interrupted_progress = TaskProgress(
        playlist_last_index=3,
        playlist_current_index=3,
        playlist_total=5,
    )
    task = _task(entries).model_copy(update={"status": "interrupted", "progress": interrupted_progress})
    queued_task: TaskResponse | None = None
    stored_task = task
    manager = TaskManager(Mock(), Mock())

    def update_task(_task_id: str, **fields: object) -> TaskResponse:
        nonlocal stored_task, queued_task
        stored_task = stored_task.model_copy(update=fields)
        if fields.get("status") == "queued":
            queued_task = stored_task
        return stored_task

    manager.storage.get_task.side_effect = lambda _task_id: stored_task
    manager.storage.update_task.side_effect = update_task
    manager.queue = Mock()
    manager.queue.put = AsyncMock()
    manager._publish = AsyncMock()
    manager._add_history_if_available = Mock()
    manager._execute_download = AsyncMock(
        side_effect=lambda *_args, **_kwargs: ([], 0, "/downloads/video-3.mp4", _args[2])
    )

    await manager.retry_playlist_item(task.id, 3)

    assert queued_task is not None
    assert queued_task.progress.playlist_completed_indexes == [1, 2]
    assert queued_task.progress.playlist_last_index == 3

    await manager._retry_playlist_item(queued_task, 3)

    assert stored_task.status == "interrupted"
    assert stored_task.progress.playlist_completed_indexes == [1, 2, 3]
    assert stored_task.progress.percent == 60.0
    assert 4 not in stored_task.progress.playlist_completed_indexes
    assert 5 not in stored_task.progress.playlist_completed_indexes


@pytest.mark.anyio
async def test_playlist_retry_uses_entry_url() -> None:
    entry = PlaylistEntry(index=7, url="https://www.youtube.com/watch?v=video-7")
    task = _task([entry]).model_copy(update={"status": "failed"})
    manager = TaskManager(Mock(), Mock())
    manager.storage.get_task.return_value = task.model_copy(update={"status": "running"})
    manager.storage.update_task.side_effect = lambda *_args, **fields: task.model_copy(update=fields)
    manager._publish = AsyncMock()
    manager._add_history_if_available = Mock()
    manager._execute_download = AsyncMock(return_value=([], 0, "/downloads/video.mp4", TaskProgress()))

    await manager._retry_playlist_item(task, entry.index)

    request = manager._execute_download.await_args.args[1]
    assert request.url == entry.url
    assert request.playlist_items is None
    assert request.playlist_entries == []
    assert request.filename_template == "Course/07-%(title)s.%(ext)s"
