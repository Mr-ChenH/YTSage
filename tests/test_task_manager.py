from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from ytsage.server.models import CreateTaskRequest, PlaylistEntry, TaskProgress, TaskResponse
from ytsage.server.services.storage import Storage
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
async def test_start_requeues_tasks_left_active_by_previous_process(tmp_path: Path) -> None:
    storage = Storage(tmp_path / "tasks.db")
    task = storage.create_task("restart-task", CreateTaskRequest(url="https://example.com/video"))
    storage.update_task(task.id, status="running", error="old transient error", finished_at="2026-01-01T00:00:00+00:00")
    manager = TaskManager(Mock(queue_concurrency=0), storage)

    await manager.start()

    recovered = storage.get_task(task.id)
    assert recovered.status == "queued"
    assert recovered.error is None
    assert recovered.finished_at is None
    assert await manager.queue.get() == task.id
    manager.queue.task_done()
    await manager.stop()


@pytest.mark.anyio
async def test_recovered_playlist_skips_completed_items_and_continues_pending() -> None:
    entries = [
        PlaylistEntry(index=index, url=f"https://www.youtube.com/watch?v=video-{index}")
        for index in range(1, 5)
    ]
    progress = TaskProgress(
        playlist_current_index=3,
        playlist_last_index=3,
        playlist_total=4,
        playlist_completed_indexes=[1, 2],
    )
    task = _task(entries).model_copy(update={"status": "queued", "progress": progress})
    stored_task = task
    manager = TaskManager(Mock(), Mock())

    def update_task(_task_id: str, **fields: object) -> TaskResponse:
        nonlocal stored_task
        stored_task = stored_task.model_copy(update=fields)
        return stored_task

    manager.storage.get_task.side_effect = lambda _task_id: stored_task
    manager.storage.update_task.side_effect = update_task
    manager._publish = AsyncMock()
    downloaded_urls: list[str] = []

    async def execute(_task: TaskResponse, request: CreateTaskRequest, item_progress: TaskProgress, **_kwargs: object):
        downloaded_urls.append(request.url)
        return [], 0, f"/downloads/video-{len(downloaded_urls) + 2}.mp4", item_progress

    manager._execute_download = AsyncMock(side_effect=execute)

    _, return_code, _, resumed_progress = await manager._execute_playlist_entries(
        task, CreateTaskRequest(**task.options), entries, progress
    )

    assert return_code == 0
    assert downloaded_urls == [entries[2].url, entries[3].url]
    assert resumed_progress.playlist_completed_indexes == [1, 2, 3, 4]
    assert resumed_progress.percent == 100.0


@pytest.mark.anyio
async def test_recovered_legacy_playlist_resumes_from_interrupted_item() -> None:
    entries = [
        PlaylistEntry(index=index, url=f"https://www.youtube.com/watch?v=video-{index}")
        for index in range(1, 5)
    ]
    progress = TaskProgress(playlist_current_index=3, playlist_last_index=3, playlist_total=4)
    task = _task(entries).model_copy(update={"status": "queued", "progress": progress})
    stored_task = task
    manager = TaskManager(Mock(), Mock())

    def update_task(_task_id: str, **fields: object) -> TaskResponse:
        nonlocal stored_task
        stored_task = stored_task.model_copy(update=fields)
        return stored_task

    manager.storage.get_task.side_effect = lambda _task_id: stored_task
    manager.storage.update_task.side_effect = update_task
    manager._publish = AsyncMock()
    manager._execute_download = AsyncMock(
        side_effect=lambda _task, request, item_progress, **_kwargs: ([], 0, request.url, item_progress)
    )

    await manager._execute_playlist_entries(task, CreateTaskRequest(**task.options), entries, progress)

    downloaded_urls = [call.args[1].url for call in manager._execute_download.await_args_list]
    assert downloaded_urls == [entries[2].url, entries[3].url]
    assert stored_task.progress.playlist_completed_indexes == [1, 2, 3, 4]


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
