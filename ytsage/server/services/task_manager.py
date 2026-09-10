"""Async download task manager."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import ServerConfig
from ..downloads.executor import DownloadExecutor
from ..downloads.playlist import copy_progress, parse_queue_item, playlist_entries, playlist_entry_filename_template, playlist_item_filename_template
from ..downloads.process import decode_output_line, terminate_process
from ..models import CreateTaskRequest, HistoryEntry, PlaylistEntry, TaskEvent, TaskProgress, TaskResponse
from .cookies import COOKIE_PROFILES, cookie_file_path, cookie_profile_for_url
from .files import classify_file
from .storage import Storage, utc_now

if TYPE_CHECKING:
    from .accounts import AccountService


def _decode_output_line(raw: bytes) -> str:
    return decode_output_line(raw)


def _playlist_item_filename_template(template: str, title: str, index: int) -> str:
    return playlist_item_filename_template(template, title, index)


def _playlist_entry_filename_template(template: str, title: str, entry: PlaylistEntry) -> str:
    return playlist_entry_filename_template(template, title, entry)


class TaskManager:
    def __init__(self, config: ServerConfig, storage: Storage, account_service: AccountService | None = None) -> None:
        self.config = config
        self.storage = storage
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.subscribers: set[asyncio.Queue[TaskEvent]] = set()
        self.account_service = account_service
        self.executor = DownloadExecutor(config, storage, self.processes, self._publish, account_service)
        self._workers: list[asyncio.Task[Any]] = []
        self._claimed_tasks: set[str] = set()
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._repair_playlist_history()
        recovered_tasks = self.storage.recover_interrupted_tasks()
        self._started = True
        for task in recovered_tasks:
            await self.queue.put(task.id)
        for index in range(self.config.queue_concurrency):
            self._workers.append(asyncio.create_task(self._worker(index)))

    async def stop(self) -> None:
        for process in list(self.processes.values()):
            self._terminate_process(process)
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False

    async def create_task(self, request: CreateTaskRequest) -> TaskResponse:
        request = request.model_copy(deep=True)
        if any(not entry.is_available for entry in request.playlist_entries):
            raise ValueError("Unavailable playlist entries cannot be downloaded.")
        if request.cookie_file:
            supplied = Path(request.cookie_file).resolve()
            allowed = {cookie_file_path(self.config.config_dir, profile).resolve() for profile in COOKIE_PROFILES}
            if supplied not in allowed:
                raise ValueError("Custom cookie file paths are not allowed.")
        if request.account_id:
            if self.account_service is None:
                raise ValueError("Account selection is unavailable.")
            expected_platform = cookie_profile_for_url(request.url)
            self.account_service.resolve_cookie_file(request.account_id, expected_platform)
            expandable = any(entry.entry_type in {"multipart_video", "favorite_collection"} for entry in request.playlist_entries)
            if expandable:
                if expected_platform != "bilibili":
                    raise ValueError("Nested playlist entries are only supported for Bilibili accounts.")
                expanded_entries = await asyncio.to_thread(
                    self.account_service.expand_playlist_entries,
                    request.account_id,
                    request.playlist_entries,
                )
                request.playlist_entries = [entry for entry in expanded_entries if entry.is_available]
                if not request.playlist_entries:
                    raise ValueError("The selected Bilibili collection contains no downloadable videos.")
        task_id = uuid.uuid4().hex
        task = self.storage.create_task(task_id, request)
        await self.queue.put(task_id)
        await self._publish("task_created", task)
        return task

    async def resume_task(self, task_id: str) -> TaskResponse:
        task = self.storage.get_task(task_id)
        if task.status not in {"failed", "cancelled", "interrupted"}:
            raise ValueError(f"Task in {task.status} state cannot be resumed")
        progress = self._copy_progress(task.progress)
        progress.speed = None
        progress.eta = None
        progress.playlist_current_index = None
        if self._playlist_entries(task):
            progress.playlist_failed_indexes = []
            progress.playlist_failures = {}
        progress.status_text = "Resume queued"
        resumed = self.storage.update_task(
            task_id,
            status="queued",
            progress=progress,
            error=None,
            finished_at=None,
        )
        await self.queue.put(task_id)
        await self._publish("task_resumed", resumed)
        return resumed

    async def restart_task(self, task_id: str) -> TaskResponse:
        task = self.storage.get_task(task_id)
        if task.status in {"queued", "running"}:
            raise ValueError(f"Task in {task.status} state cannot be restarted")
        return await self.create_task(CreateTaskRequest(**task.options))

    async def retry_playlist_item(self, task_id: str, playlist_index: int) -> TaskResponse:
        task = self.storage.get_task(task_id)
        entries = self._playlist_entries(task)
        entry = next((item for item in entries if item.index == playlist_index), None)
        if entry is None:
            raise KeyError(f"playlist item {playlist_index} not found")
        if not entry.is_available:
            raise ValueError("Unavailable playlist entries cannot be retried.")
        progress = self._copy_progress(task.progress)
        if not progress.playlist_completed_indexes and progress.playlist_last_index:
            progress.playlist_completed_indexes = [
                item.index for item in entries if item.index < progress.playlist_last_index
            ]
        failures = dict(progress.playlist_failures)
        failures.pop(str(playlist_index), None)
        progress.playlist_failures = failures
        progress.playlist_current_index = None
        progress.status_text = f"Retry queued for playlist item {playlist_index}"
        updated = self.storage.update_task(task_id, status="queued", progress=progress, error=None, finished_at=None)
        await self.queue.put(f"{task_id}:{playlist_index}")
        await self._publish("task_retry_queued", updated)
        return updated

    def list_tasks(self, limit: int = 100, offset: int = 0, active_only: bool = False) -> list[TaskResponse]:
        return self.storage.list_tasks(limit=limit, offset=offset, active_only=active_only)

    def get_task(self, task_id: str) -> TaskResponse:
        return self.storage.get_task(task_id)

    async def cancel_task(self, task_id: str) -> TaskResponse:
        task = self.storage.get_task(task_id)
        process = self.processes.get(task_id)
        if process is not None:
            self._terminate_process(process)
        task = self.storage.update_task(task_id, status="cancelled", finished_at=utc_now())
        await self._publish("task_cancelled", task)
        return task

    async def delete_task(self, task_id: str) -> None:
        try:
            task = self.storage.get_task(task_id)
        except KeyError:
            raise
        process = self.processes.get(task_id)
        if process is not None:
            self._terminate_process(process)
        self.storage.delete_task(task_id)
        await self._publish("task_deleted", task)

    def clear_finished_tasks(self) -> int:
        return self.storage.clear_finished_tasks()

    async def subscribe(self) -> asyncio.Queue[TaskEvent]:
        queue: asyncio.Queue[TaskEvent] = asyncio.Queue(maxsize=100)
        self.subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[TaskEvent]) -> None:
        self.subscribers.discard(queue)

    async def _worker(self, index: int) -> None:
        while True:
            queue_item = await self.queue.get()
            task_id, retry_index = self._parse_queue_item(queue_item)
            try:
                task = self.storage.get_task(task_id)
            except KeyError:
                self.queue.task_done()
                continue
            try:
                if task.status != "queued":
                    continue
                if task_id in self._claimed_tasks:
                    await asyncio.sleep(0.05)
                    await self.queue.put(queue_item)
                    continue
                self._claimed_tasks.add(task_id)
                if retry_index is None:
                    await self._run_task(task)
                else:
                    await self._retry_playlist_item(task, retry_index)
            finally:
                self._claimed_tasks.discard(task_id)
                self.queue.task_done()

    async def _run_task(self, task: TaskResponse) -> None:
        request = CreateTaskRequest(**task.options)
        progress = task.progress
        entries = self._playlist_entries(task)
        if entries:
            output_tail, return_code, output_path, progress = await self._execute_playlist_entries(task, request, entries, progress)
        else:
            output_tail, return_code, output_path, progress = await self._execute_with_youtube_fallback(task, request, progress)
        if self.storage.get_task(task.id).status == "cancelled":
            return

        has_playlist_failures = bool(progress.playlist_failed_indexes)
        if return_code == 0:
            progress_data = progress.model_dump() if hasattr(progress, "model_dump") else progress.dict()
            completed_progress = TaskProgress(**progress_data)
            completed_progress.percent = 100.0
            final_status = "failed" if has_playlist_failures else "completed"
            completed = self.storage.update_task(
                task.id,
                status=final_status,
                progress=completed_progress,
                output_path=output_path,
                error="\n".join(output_tail[-8:]) if has_playlist_failures else None,
                finished_at=utc_now(),
            )
            self._add_history_if_available(task, output_path)
            await self._publish("task_failed" if has_playlist_failures else "task_completed", completed)
        else:
            failed = self.storage.update_task(
                task.id,
                status="failed",
                error="\n".join(output_tail[-8:]) or f"yt-dlp exited with code {return_code}",
                finished_at=utc_now(),
            )
            await self._publish("task_failed", failed)

    async def _execute_playlist_entries(
        self,
        task: TaskResponse,
        request: CreateTaskRequest,
        entries: list[PlaylistEntry],
        progress: TaskProgress,
    ) -> tuple[list[str], int, str | None, TaskProgress]:
        all_output: list[str] = []
        last_output_path: str | None = None
        progress = self._copy_progress(progress)
        completed_indexes = set(progress.playlist_completed_indexes)
        if not completed_indexes and progress.playlist_last_index:
            completed_indexes.update(
                entry.index for entry in entries if entry.index < progress.playlist_last_index
            )
            progress.playlist_completed_indexes = sorted(completed_indexes)
        pending_entries = [entry for entry in entries if entry.index not in completed_indexes]

        for entry in pending_entries:
            if self.storage.get_task(task.id).status == "cancelled":
                break
            item_request = request.model_copy(deep=True)
            item_request.url = entry.url or entry.webpage_url or request.url
            item_request.playlist_items = None
            item_request.playlist_entries = []
            item_request.filename_template = _playlist_entry_filename_template(
                request.filename_template,
                request.playlist_title or "playlist",
                entry,
            )
            progress.playlist_current_index = entry.index
            progress.playlist_last_index = entry.index
            progress.playlist_total = len(entries)
            progress.percent = None
            progress.speed = None
            progress.eta = None
            progress.current_filename = None
            progress.downloaded_bytes = None
            progress.total_bytes = None
            completed_count = len(progress.playlist_completed_indexes)
            progress.status_text = f"Downloading playlist item {completed_count + 1} of {len(entries)}"

            output, return_code, output_path, progress = await self._execute_with_youtube_fallback(
                task,
                item_request,
                progress,
                fallback_status=f"Downloaded playlist item {completed_count + 1} at 360p after YouTube rejected the selected format",
            )
            item_error = next((line for line in reversed(output) if "ERROR:" in line), None)
            all_output.extend(output)
            all_output = all_output[-20:]
            if output_path:
                last_output_path = output_path
            failures = dict(progress.playlist_failures)
            failed_indexes = list(progress.playlist_failed_indexes)
            completed_indexes = list(progress.playlist_completed_indexes)
            if return_code != 0:
                completed_indexes = [index for index in completed_indexes if index != entry.index]
                if entry.index not in failed_indexes:
                    failed_indexes.append(entry.index)
                failures[str(entry.index)] = item_error.removeprefix("ERROR:").strip() if item_error else ("\n".join(output[-8:]) or f"yt-dlp exited with code {return_code}")
            else:
                failed_indexes = [index for index in failed_indexes if index != entry.index]
                failures.pop(str(entry.index), None)
                if entry.index not in completed_indexes:
                    completed_indexes.append(entry.index)
                if not progress.status_text or progress.status_text.startswith("ERROR:"):
                    progress.status_text = f"Downloaded playlist item {len(completed_indexes)} of {len(entries)}"
            progress.playlist_failed_indexes = failed_indexes
            progress.playlist_completed_indexes = sorted(completed_indexes)
            progress.playlist_failures = failures
            progress.playlist_current_index = None
            progress.playlist_last_index = entry.index
            progress.percent = len(completed_indexes) / len(entries) * 100
            updated = self.storage.update_task(task.id, progress=progress)
            await self._publish("task_progress", updated)

        return all_output, 0, last_output_path, progress

    async def _retry_playlist_item(self, task: TaskResponse, playlist_index: int) -> None:
        entries = self._playlist_entries(task)
        entry = next((item for item in entries if item.index == playlist_index), None)
        if entry is None:
            return
        request = CreateTaskRequest(**task.options)
        request.url = entry.url or entry.webpage_url or request.url
        request.playlist_items = None
        request.playlist_entries = []
        request.filename_template = _playlist_entry_filename_template(
            request.filename_template,
            request.playlist_title or "playlist",
            entry,
        )
        progress = self._copy_progress(task.progress)
        progress.playlist_current_index = playlist_index
        progress.percent = None
        progress.speed = None
        progress.eta = None
        progress.current_filename = None
        progress.downloaded_bytes = None
        progress.total_bytes = None
        progress.status_text = f"Retrying playlist item {playlist_index}"
        output_tail, return_code, output_path, progress = await self._execute_with_youtube_fallback(
            task,
            request,
            progress,
            fallback_status=f"Downloaded playlist item {playlist_index} at 360p after YouTube rejected the selected format",
        )
        if self.storage.get_task(task.id).status == "cancelled":
            return

        failed_indexes = [item for item in progress.playlist_failed_indexes if item != playlist_index]
        failures = dict(progress.playlist_failures)
        failures.pop(str(playlist_index), None)
        if return_code == 0:
            completed_indexes = set(progress.playlist_completed_indexes)
            completed_indexes.add(playlist_index)
            progress.playlist_failed_indexes = failed_indexes
            progress.playlist_completed_indexes = sorted(completed_indexes)
            progress.playlist_failures = failures
            progress.playlist_current_index = None
            progress.percent = len(completed_indexes) / len(entries) * 100
            remaining_failures = bool(progress.playlist_failed_indexes)
            all_completed = all(entry.index in completed_indexes for entry in entries)
            updated = self.storage.update_task(
                task.id,
                status="completed" if all_completed and not remaining_failures else ("failed" if remaining_failures else "interrupted"),
                progress=progress,
                output_path=output_path or task.output_path,
                error=None if not remaining_failures else task.error,
                finished_at=utc_now(),
            )
            self._add_history_if_available(task, output_path)
            await self._publish("task_retry_completed", updated)
            return

        if playlist_index not in progress.playlist_failed_indexes:
            progress.playlist_failed_indexes = [*progress.playlist_failed_indexes, playlist_index]
        progress.playlist_completed_indexes = [index for index in progress.playlist_completed_indexes if index != playlist_index]
        failures[str(playlist_index)] = "\n".join(output_tail[-8:]) or f"yt-dlp exited with code {return_code}"
        progress.playlist_failures = failures
        progress.playlist_current_index = None
        failed = self.storage.update_task(
            task.id,
            status="failed",
            progress=progress,
            error=failures[str(playlist_index)],
            finished_at=utc_now(),
        )
        await self._publish("task_retry_failed", failed)

    async def _execute_with_youtube_fallback(
        self,
        task: TaskResponse,
        request: CreateTaskRequest,
        progress: TaskProgress,
        fallback_status: str = "Downloaded at 360p after YouTube rejected the selected format",
    ) -> tuple[list[str], int, str | None, TaskProgress]:
        output, return_code, output_path, progress = await self._execute_download(task, request, progress)
        error = next((line for line in reversed(output) if "ERROR:" in line), None)
        if return_code == 0 or not error or "HTTP Error 403" not in error or "youtube.com" not in request.url:
            return output, return_code, output_path, progress
        fallback_request = request.model_copy(deep=True)
        fallback_request.format_id = "18"
        fallback_request.cookie_file = None
        progress.status_text = "YouTube blocked the selected format; retrying at 360p"
        fallback_output, fallback_code, fallback_path, progress = await self._execute_download(task, fallback_request, progress, use_cookies=False)
        output.extend(fallback_output)
        if fallback_code == 0:
            progress.status_text = fallback_status
            return output, 0, fallback_path, progress
        return output, fallback_code, fallback_path, progress

    async def _execute_download(
        self,
        task: TaskResponse,
        request: CreateTaskRequest,
        progress: TaskProgress,
        *,
        use_cookies: bool = True,
    ) -> tuple[list[str], int, str | None, TaskProgress]:
        return await self.executor.execute(task, request, progress, use_cookies=use_cookies)

    def _parse_queue_item(self, queue_item: str) -> tuple[str, int | None]:
        return parse_queue_item(queue_item)

    def _playlist_entries(self, task: TaskResponse) -> list[PlaylistEntry]:
        return playlist_entries(task)

    def _copy_progress(self, progress: TaskProgress) -> TaskProgress:
        return copy_progress(progress)

    def _playlist_history_details(self, task: TaskResponse, path: Path) -> tuple[str, Path, int, str, dict[str, Any]]:
        playlist_title = task.options.get("playlist_title")
        is_playlist = isinstance(playlist_title, str) and bool(playlist_title.strip())
        entries = task.options.get("playlist_entries")
        completed_count = len(task.progress.playlist_completed_indexes)
        playlist_count = completed_count or task.progress.playlist_total or (len(entries) if isinstance(entries, list) else 0)
        output = path
        template = task.options.get("filename_template")
        download_root = getattr(self.config, "download_dir", None)
        if is_playlist and isinstance(template, str) and "%(playlist_title)" in template and isinstance(download_root, Path):
            candidate = path if path.is_dir() else path.parent
            try:
                candidate.resolve().relative_to(download_root.resolve())
                rendered_template = _playlist_item_filename_template(template, playlist_title, 1).replace("\\", "/")
                template_directory = rendered_template.rpartition("/")[0]
                if template_directory and "%(" not in template_directory:
                    expected_root = download_root.joinpath(*template_directory.split("/"))
                    expected_root.resolve().relative_to(download_root.resolve())
                    candidate.resolve().relative_to(expected_root.resolve())
                    output = expected_root
                elif candidate.resolve() != download_root.resolve():
                    output = candidate
            except (ValueError, OSError):
                pass
        if output.is_dir():
            files = [item for item in output.rglob("*") if item.is_file()]
            file_size = sum(item.stat().st_size for item in files)
            media_type = {"video": "video", "audio": "audio", "subtitles": "subtitle"}.get(task.mode, "other")
        else:
            file_size = output.stat().st_size
            media_type = classify_file(output)
        metadata = {
            "mode": task.mode,
            "is_playlist": is_playlist,
            "playlist_count": playlist_count,
            "output_is_directory": output.is_dir(),
        }
        title = playlist_title.strip() if is_playlist else path.stem
        return title, output, file_size, media_type, metadata

    def _repair_playlist_history(self) -> None:
        if not isinstance(getattr(self.config, "download_dir", None), Path):
            return
        for history in self.storage.list_history(limit=100_000):
            if not history.task_id:
                continue
            try:
                task = self.storage.get_task(history.task_id)
                path = Path(history.output_path or "")
                if not path.exists() or not task.options.get("playlist_title"):
                    continue
                title, output, file_size, media_type, metadata = self._playlist_history_details(task, path)
                self.storage.update_history(history.model_copy(update={
                    "title": title,
                    "output_path": str(output),
                    "file_size": file_size,
                    "media_type": media_type,
                    "metadata": {**history.metadata, **metadata},
                }))
            except (KeyError, OSError):
                continue

    def _add_history_if_available(self, task: TaskResponse, output_path: str | None) -> None:
        if not output_path:
            return
        path = Path(output_path)
        if not path.exists():
            return
        title, output, file_size, media_type, metadata = self._playlist_history_details(task, path)
        self.storage.add_history(
            HistoryEntry(
                id=uuid.uuid4().hex,
                task_id=task.id,
                url=task.url,
                title=title,
                output_path=str(output),
                file_size=file_size,
                media_type=media_type,
                status="completed",
                downloaded_at=utc_now(),
                metadata=metadata,
            )
        )

    def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        terminate_process(process)

    async def _publish(self, event_type: str, task: TaskResponse) -> None:
        event = TaskEvent(type=event_type, task=task)
        dead: list[asyncio.Queue[TaskEvent]] = []
        for subscriber in self.subscribers:
            try:
                subscriber.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(subscriber)
        for subscriber in dead:
            self.subscribers.discard(subscriber)
