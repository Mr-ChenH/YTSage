from __future__ import annotations

import asyncio
import uuid
from typing import Callable

from ..models import AnalyzeRequest, AnalyzeResponse, CreateTaskRequest, PageInfo, PlaylistEntry, PlaylistMonitorCreate, PlaylistMonitorCreateResponse, PlaylistMonitorLogListResponse, PlaylistMonitorResponse
from .storage import Storage, utc_now
from .task_manager import TaskManager

AnalyzeCallback = Callable[[AnalyzeRequest], AnalyzeResponse]


def playlist_entry_key(entry: PlaylistEntry) -> str:
    if entry.id:
        return f"id:{entry.id}"
    url = entry.webpage_url or entry.url
    if url:
        return f"url:{url.rstrip('/')}"
    return f"index:{entry.index}:{entry.title or ''}"


class PlaylistMonitorService:
    def __init__(self, storage: Storage, task_manager: TaskManager, analyze: AnalyzeCallback) -> None:
        self.storage = storage
        self.task_manager = task_manager
        self.analyze = analyze
        self._runner: asyncio.Task[None] | None = None
        self._wake = asyncio.Event()
        self._checking: set[str] = set()

    async def start(self) -> None:
        if self._runner is None:
            for monitor in self.storage.list_monitors():
                _logs, total = self.storage.list_monitor_logs(monitor.id, limit=1)
                if total == 0:
                    self.storage.append_monitor_log(
                        monitor.id, "logging_enabled", "Run logging enabled for this existing monitor."
                    )
            self._runner = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._runner is None:
            return
        self._runner.cancel()
        await asyncio.gather(self._runner, return_exceptions=True)
        self._runner = None

    async def create(self, request: PlaylistMonitorCreate) -> PlaylistMonitorCreateResponse:
        account_id = request.account_id or request.download_options.account_id
        analysis = await asyncio.to_thread(self.analyze, AnalyzeRequest(url=request.url, account_id=account_id))
        if not analysis.is_playlist:
            raise ValueError("URL did not resolve to a playlist or collection")

        normalized = request.model_copy(deep=True)
        normalized.account_id = account_id
        normalized.download_options.url = request.url
        normalized.download_options.account_id = account_id
        initial_request = request.download_options.model_copy(deep=True)
        initial_request.url = request.url
        initial_request.account_id = account_id
        if not initial_request.playlist_entries:
            initial_request.playlist_entries = [entry for entry in analysis.playlist_entries if entry.is_available]
        else:
            initial_request.playlist_entries = [entry for entry in initial_request.playlist_entries if entry.is_available]
        initial_request.playlist_items = None
        normalized.download_options.playlist_entries = []
        normalized.download_options.playlist_items = None
        monitor = self.storage.create_monitor(uuid.uuid4().hex, normalized)
        task = None
        try:
            current_keys = [playlist_entry_key(entry) for entry in analysis.playlist_entries]
            monitor = self.storage.schedule_next_monitor_check(
                monitor.id,
                monitor.interval_minutes,
                title=analysis.title,
                seen_entry_keys=current_keys,
                last_checked_at=utc_now(),
                last_error=None,
            )
            if initial_request.playlist_entries:
                initial_request.task_origin = "monitor_initial"
                initial_request.monitor_id = monitor.id
                initial_request.monitor_detected_at = utc_now()
                initial_request.monitor_new_item_count = len(initial_request.playlist_entries)
                task = await self.task_manager.create_task(initial_request)
                monitor = self.storage.update_monitor(monitor.id, last_task_id=task.id)
            self.storage.append_monitor_log(
                monitor.id,
                "monitor_created",
                "Monitor initialized and initial download queued." if task else "Monitor initialized; collection is currently empty.",
                details={
                    "known_items": len(current_keys),
                    "new_items": len(initial_request.playlist_entries),
                    "task_id": task.id if task else None,
                },
            )
        except Exception:
            if task is not None:
                try:
                    await self.task_manager.delete_task(task.id)
                except Exception:
                    pass
            self.storage.delete_monitor(monitor.id)
            raise
        self._wake.set()
        return PlaylistMonitorCreateResponse(monitor=monitor, initial_task=task)

    def list(self) -> list[PlaylistMonitorResponse]:
        return self.storage.list_monitors()

    def list_logs(self, monitor_id: str, offset: int = 0, limit: int = 50) -> PlaylistMonitorLogListResponse:
        items, total = self.storage.list_monitor_logs(monitor_id, limit=limit, offset=offset)
        return PlaylistMonitorLogListResponse(
            items=items,
            page=PageInfo(offset=offset, limit=limit, total=total, has_more=offset + len(items) < total),
        )

    def update(self, monitor_id: str, enabled: bool | None, interval_minutes: int | None) -> PlaylistMonitorResponse:
        monitor = self.storage.get_monitor(monitor_id)
        fields: dict[str, object] = {}
        if enabled is not None:
            fields["enabled"] = enabled
        if interval_minutes is not None:
            fields["interval_minutes"] = interval_minutes
        updated = self.storage.schedule_next_monitor_check(
            monitor_id,
            interval_minutes or monitor.interval_minutes,
            **fields,
        )
        self.storage.append_monitor_log(
            monitor_id, "settings_updated", "Monitor settings updated.",
            details={"enabled": updated.enabled, "interval_minutes": updated.interval_minutes},
        )
        self._wake.set()
        return updated

    def delete(self, monitor_id: str) -> None:
        self.storage.delete_monitor(monitor_id)
        self._wake.set()

    async def check_now(self, monitor_id: str) -> PlaylistMonitorResponse:
        if monitor_id in self._checking:
            return self.storage.get_monitor(monitor_id)
        self._checking.add(monitor_id)
        try:
            monitor = self.storage.get_monitor(monitor_id)
            self.storage.append_monitor_log(monitor.id, "check_started", "Checking collection for updates.")
            analysis = await asyncio.to_thread(self.analyze, AnalyzeRequest(url=monitor.url, account_id=monitor.account_id))
            if not analysis.is_playlist:
                raise ValueError("URL did not resolve to a playlist or collection")
            current_keys = [playlist_entry_key(entry) for entry in analysis.playlist_entries]
            seen = set(monitor.seen_entry_keys)
            new_entries = [entry for entry in analysis.playlist_entries if entry.is_available and playlist_entry_key(entry) not in seen]
            merged_keys = [*monitor.seen_entry_keys, *(key for key in current_keys if key not in seen)]
            task_id: str | None = None
            # The first successful check establishes a baseline. Future checks download only additions.
            if monitor.last_checked_at is not None and new_entries:
                options = CreateTaskRequest(**monitor.download_options).model_copy(deep=True)
                options.url = monitor.url
                options.account_id = monitor.account_id
                collection_title = analysis.raw.get("collection_title")
                options.playlist_title = (
                    collection_title if isinstance(collection_title, str) else None
                ) or analysis.title or options.playlist_title
                options.playlist_entries = new_entries
                options.playlist_items = None
                options.task_origin = "monitor_update"
                options.monitor_id = monitor.id
                options.monitor_detected_at = utc_now()
                options.monitor_new_item_count = len(new_entries)
                task = await self.task_manager.create_task(options)
                task_id = task.id
            self.storage.append_monitor_log(
                monitor.id,
                "new_entries" if new_entries else "no_updates",
                "New entries found and download queued." if new_entries else "Check completed with no new entries.",
                details={"known_items": len(current_keys), "new_items": len(new_entries), "task_id": task_id},
            )
            return self.storage.schedule_next_monitor_check(
                monitor.id,
                monitor.interval_minutes,
                title=analysis.title,
                seen_entry_keys=merged_keys,
                last_checked_at=utc_now(),
                last_error=None,
                last_task_id=task_id or monitor.last_task_id,
            )
        except Exception as exc:
            monitor = self.storage.get_monitor(monitor_id)
            self.storage.append_monitor_log(
                monitor.id, "check_failed", str(exc) or "Monitor check failed.", level="error",
            )
            return self.storage.schedule_next_monitor_check(
                monitor.id,
                monitor.interval_minutes,
                last_checked_at=utc_now(),
                last_error=str(exc),
            )
        finally:
            self._checking.discard(monitor_id)

    async def _run(self) -> None:
        while True:
            for monitor in self.storage.list_due_monitors():
                await self.check_now(monitor.id)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=30)
            except TimeoutError:
                pass
