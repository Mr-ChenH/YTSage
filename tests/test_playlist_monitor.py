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
async def test_start_bootstraps_logging_for_existing_monitors_once(tmp_path) -> None:
    storage = Storage(tmp_path / "tasks.db")
    monitor = storage.create_monitor("monitor", _request())
    service = PlaylistMonitorService(storage, Mock(), lambda _request: _analysis([]))

    await service.start()
    await service.stop()
    await service.start()
    await service.stop()

    logs, total = storage.list_monitor_logs(monitor.id)
    assert total == 1
    assert logs[0].event == "logging_enabled"


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
    assert initial_request.task_origin == "monitor_initial"
    assert initial_request.monitor_id == monitor.id
    assert initial_request.monitor_new_item_count == 1
    assert initial_request.monitor_detected_at is not None
    assert monitor.seen_entry_keys == ["id:one"]
    assert monitor.download_options["playlist_entries"] == []
    assert monitor.download_options["playlist_items"] is None
    assert monitor.last_checked_at is not None
    assert monitor.last_task_id == "download-task"
    created_logs, created_total = service.storage.list_monitor_logs(monitor.id)
    assert created_total == 1
    assert created_logs[0].event == "monitor_created"
    assert created_logs[0].details["known_items"] == 1

    task_manager.create_task.reset_mock()
    checked = await service.check_now(monitor.id)

    task_manager.create_task.assert_awaited_once()
    download_request = task_manager.create_task.await_args.args[0]
    assert [entry.id for entry in download_request.playlist_entries] == ["two"]
    assert download_request.playlist_items is None
    assert download_request.task_origin == "monitor_update"
    assert download_request.monitor_id == monitor.id
    assert download_request.monitor_new_item_count == 1
    assert download_request.monitor_detected_at is not None
    assert checked.seen_entry_keys == ["id:one", "id:two"]
    assert checked.last_task_id == "download-task"
    assert checked.last_error is None
    logs, total = service.storage.list_monitor_logs(monitor.id)
    assert total == 3
    assert [log.event for log in logs] == ["new_entries", "check_started", "monitor_created"]
    assert logs[0].details["new_items"] == 1


@pytest.mark.anyio
async def test_monitor_excludes_unavailable_entries_from_downloads(tmp_path) -> None:
    entries = [
        PlaylistEntry(index=1, id="one", url="https://example.com/one"),
        PlaylistEntry(index=2, id="gone", is_available=False, unavailable_reason="Removed"),
    ]
    task_manager = Mock(create_task=AsyncMock(return_value=TaskResponse(
        id="task", url="https://example.com/playlist", mode="video", status="queued", progress=TaskProgress(),
        created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
    )))
    service = PlaylistMonitorService(Storage(tmp_path / "tasks.db"), task_manager, lambda _request: _analysis(entries))

    result = await service.create(_request())

    initial_request = task_manager.create_task.await_args.args[0]
    assert [entry.id for entry in initial_request.playlist_entries] == ["one"]
    assert result.monitor.seen_entry_keys == ["id:one", "id:gone"]


@pytest.mark.anyio
async def test_monitor_allows_collection_with_only_unavailable_entries(tmp_path) -> None:
    entries = [PlaylistEntry(index=1, id="gone", is_available=False, unavailable_reason="Removed")]
    task_manager = Mock(create_task=AsyncMock())
    service = PlaylistMonitorService(Storage(tmp_path / "tasks.db"), task_manager, lambda _request: _analysis(entries))

    result = await service.create(_request())

    assert result.initial_task is None
    assert result.monitor.seen_entry_keys == ["id:gone"]
    task_manager.create_task.assert_not_awaited()


@pytest.mark.anyio
async def test_empty_collection_monitor_downloads_first_future_entry(tmp_path) -> None:
    added = PlaylistEntry(index=1, id="new", url="https://example.com/new")
    analyses = iter([_analysis([]), _analysis([added])])
    task = TaskResponse(
        id="new-task", url="https://example.com/playlist", mode="video", status="queued",
        progress=TaskProgress(), created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
    )
    task_manager = Mock(create_task=AsyncMock(return_value=task))
    service = PlaylistMonitorService(Storage(tmp_path / "tasks.db"), task_manager, lambda _request: next(analyses))

    created = await service.create(_request())
    checked = await service.check_now(created.monitor.id)

    assert created.initial_task is None
    assert created.monitor.seen_entry_keys == []
    assert created.monitor.last_checked_at is not None
    task_manager.create_task.assert_awaited_once()
    assert [entry.id for entry in task_manager.create_task.await_args.args[0].playlist_entries] == ["new"]
    assert checked.seen_entry_keys == ["id:new"]
    assert checked.last_task_id == "new-task"


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
async def test_monitor_propagates_account_to_analysis_and_tasks(tmp_path) -> None:
    request = _request()
    request.account_id = "bilibili-account"
    analyses = []
    task_manager = Mock()
    task_manager.create_task = AsyncMock(return_value=TaskResponse(
        id="task", url=request.url, mode="video", status="queued", progress=TaskProgress(),
        created_at="2026-01-01T00:00:00+00:00", updated_at="2026-01-01T00:00:00+00:00",
    ))
    service = PlaylistMonitorService(Storage(tmp_path / "tasks.db"), task_manager, lambda analysis_request: analyses.append(analysis_request) or _analysis([PlaylistEntry(index=1, id="one", url="https://example.com/one")]))

    result = await service.create(request)
    await service.check_now(result.monitor.id)

    assert result.monitor.account_id == "bilibili-account"
    assert all(item.account_id == "bilibili-account" for item in analyses)
    assert task_manager.create_task.await_args_list[0].args[0].account_id == "bilibili-account"


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
    logs, total = storage.list_monitor_logs(monitor.id)
    assert total == 2
    assert [log.event for log in logs] == ["check_failed", "check_started"]
    assert logs[0].level == "error"


def test_monitor_log_pagination_and_delete_cleanup(tmp_path) -> None:
    storage = Storage(tmp_path / "tasks.db")
    monitor = storage.create_monitor("monitor", _request())
    for index in range(3):
        storage.append_monitor_log(monitor.id, "check", f"Check {index}")

    logs, total = storage.list_monitor_logs(monitor.id, limit=2, offset=1)

    assert total == 3
    assert [log.message for log in logs] == ["Check 1", "Check 0"]
    storage.delete_monitor(monitor.id)
    with pytest.raises(KeyError):
        storage.list_monitor_logs(monitor.id)
    assert storage._conn.execute("SELECT COUNT(*) FROM playlist_monitor_logs WHERE monitor_id = ?", (monitor.id,)).fetchone()[0] == 0


def test_duplicate_monitor_url_is_rejected(tmp_path) -> None:
    storage = Storage(tmp_path / "tasks.db")
    storage.create_monitor("first", _request())

    with pytest.raises(ValueError, match="already monitored"):
        storage.create_monitor("second", _request())



def test_playlist_entry_key_prefers_stable_id() -> None:
    first = PlaylistEntry(index=1, id="video", url="https://example.com/watch?v=video")
    moved = PlaylistEntry(index=8, id="video", url="https://example.com/watch?v=video&list=playlist")

    assert playlist_entry_key(first) == playlist_entry_key(moved) == "id:video"
