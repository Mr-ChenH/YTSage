from unittest.mock import AsyncMock, Mock

import pytest

from ytsage.server.models import AnalyzeResponse, CreateTaskRequest, PlaylistEntry, PlaylistMonitorCreate, TaskProgress, TaskResponse
from ytsage.server.services.playlist_monitor import PlaylistMonitorService, playlist_entry_key
from ytsage.server.services.storage import Storage


def _analysis(entries: list[PlaylistEntry]) -> AnalyzeResponse:
    return AnalyzeResponse(
        url="https://example.com/playlist",
        title="Course",
        is_playlist=True,
        playlist_count=len(entries),
        playlist_entries=entries,
    )


def _request() -> PlaylistMonitorCreate:
    options = CreateTaskRequest(
        url="https://example.com/playlist",
        format_id=None,
        playlist_title="Course",
        filename_template="%(playlist_title)s/%(playlist_index)02d-%(title)s.%(ext)s",
    )
    return PlaylistMonitorCreate(url=options.url, interval_minutes=60, download_options=options)


@pytest.mark.anyio
async def test_monitor_downloads_current_selection_then_only_new_entries(tmp_path) -> None:
    first_entries = [PlaylistEntry(index=1, id="one", url="https://example.com/one")]
    updated_entries = [*first_entries, PlaylistEntry(index=2, id="two", url="https://example.com/two")]
    analyses = iter([_analysis(first_entries), _analysis(updated_entries)])
    task_manager = Mock()
    task_manager.create_task = AsyncMock(
        return_value=TaskResponse(
            id="download-task",
            url="https://example.com/playlist",
            mode="video",
            status="queued",
            progress=TaskProgress(),
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
    )
    service = PlaylistMonitorService(Storage(tmp_path / "tasks.db"), task_manager, lambda _request: next(analyses))

    monitor = (await service.create(_request())).monitor

    task_manager.create_task.assert_awaited_once()
    initial_request = task_manager.create_task.await_args.args[0]
    assert [entry.id for entry in initial_request.playlist_entries] == ["one"]
    assert monitor.seen_entry_keys == ["id:one"]
    assert monitor.download_options["playlist_entries"] == []
    assert monitor.download_options["playlist_items"] is None
    assert monitor.last_checked_at is not None
    assert monitor.last_task_id == "download-task"

    task_manager.create_task.reset_mock()
    checked = await service.check_now(monitor.id)

    task_manager.create_task.assert_awaited_once()
    download_request = task_manager.create_task.await_args.args[0]
    assert [entry.id for entry in download_request.playlist_entries] == ["two"]
    assert download_request.playlist_items is None
    assert checked.seen_entry_keys == ["id:one", "id:two"]
    assert checked.last_task_id == "download-task"
    assert checked.last_error is None


@pytest.mark.anyio
async def test_monitor_baseline_covers_unselected_existing_entries(tmp_path) -> None:
    all_entries = [
        PlaylistEntry(index=1, id="one", url="https://example.com/one"),
        PlaylistEntry(index=2, id="two", url="https://example.com/two"),
    ]
    request = _request()
    request.download_options.playlist_entries = [all_entries[1]]
    task_manager = Mock()
    task_manager.create_task = AsyncMock(
        return_value=TaskResponse(
            id="initial-task",
            url=request.url,
            mode="video",
            status="queued",
            progress=TaskProgress(),
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
    )
    service = PlaylistMonitorService(Storage(tmp_path / "tasks.db"), task_manager, lambda _request: _analysis(all_entries))

    result = await service.create(request)

    initial_request = task_manager.create_task.await_args.args[0]
    assert [entry.id for entry in initial_request.playlist_entries] == ["two"]
    assert result.monitor.seen_entry_keys == ["id:one", "id:two"]
    assert result.initial_task.id == "initial-task"


@pytest.mark.anyio
async def test_monitor_creation_rolls_back_when_initial_task_fails(tmp_path) -> None:
    storage = Storage(tmp_path / "tasks.db")
    task_manager = Mock(create_task=AsyncMock(side_effect=RuntimeError("queue unavailable")))
    entries = [PlaylistEntry(index=1, id="one", url="https://example.com/one")]
    service = PlaylistMonitorService(storage, task_manager, lambda _request: _analysis(entries))

    with pytest.raises(RuntimeError, match="queue unavailable"):
        await service.create(_request())

    assert storage.list_monitors() == []


@pytest.mark.anyio
async def test_monitor_error_keeps_baseline_and_schedules_retry(tmp_path) -> None:
    storage = Storage(tmp_path / "tasks.db")
    task_manager = Mock(create_task=AsyncMock())
    service = PlaylistMonitorService(storage, task_manager, lambda _request: (_ for _ in ()).throw(RuntimeError("network down")))
    monitor = storage.create_monitor("monitor", _request())
    storage.update_monitor(monitor.id, seen_entry_keys=["id:one"])

    checked = await service.check_now(monitor.id)

    assert checked.seen_entry_keys == ["id:one"]
    assert checked.last_error == "network down"
    assert checked.last_checked_at is not None
    assert checked.next_check_at > checked.last_checked_at
    task_manager.create_task.assert_not_awaited()


def test_duplicate_monitor_url_is_rejected(tmp_path) -> None:
    storage = Storage(tmp_path / "tasks.db")
    storage.create_monitor("first", _request())

    with pytest.raises(ValueError, match="already monitored"):
        storage.create_monitor("second", _request())



def test_playlist_entry_key_prefers_stable_id() -> None:
    first = PlaylistEntry(index=1, id="video", url="https://example.com/watch?v=video")
    moved = PlaylistEntry(index=8, id="video", url="https://example.com/watch?v=video&list=playlist")

    assert playlist_entry_key(first) == playlist_entry_key(moved) == "id:video"
