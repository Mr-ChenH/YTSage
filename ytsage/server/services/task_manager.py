"""Async download task manager."""

from __future__ import annotations

import asyncio
import locale
import os
import signal
import subprocess
import uuid
from pathlib import Path
from typing import Any

from ..config import ServerConfig
from ..models import CreateTaskRequest, HistoryEntry, PlaylistEntry, TaskEvent, TaskProgress, TaskResponse
from .cookies import cookie_file_for_url
from .download_service import build_download_command, discover_new_files, parse_progress_line, snapshot_files
from .files import classify_file
from .storage import Storage, utc_now


def _decode_output_line(raw: bytes) -> str:
    encodings = ["utf-8", "cp936", "gbk", "mbcs", locale.getpreferredencoding(False)]
    tried: set[str] = set()
    for encoding in encodings:
        normalized = encoding.lower()
        if normalized in tried:
            continue
        tried.add(normalized)
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="replace")


class TaskManager:
    def __init__(self, config: ServerConfig, storage: Storage) -> None:
        self.config = config
        self.storage = storage
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.processes: dict[str, asyncio.subprocess.Process] = {}
        self.subscribers: set[asyncio.Queue[TaskEvent]] = set()
        self._workers: list[asyncio.Task[Any]] = []
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self.storage.mark_interrupted_tasks()
        self._started = True
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
        task_id = uuid.uuid4().hex
        task = self.storage.create_task(task_id, request)
        await self.queue.put(task_id)
        await self._publish("task_created", task)
        return task

    async def retry_playlist_item(self, task_id: str, playlist_index: int) -> TaskResponse:
        task = self.storage.get_task(task_id)
        entries = self._playlist_entries(task)
        entry = next((item for item in entries if item.index == playlist_index), None)
        if entry is None:
            raise KeyError(f"playlist item {playlist_index} not found")
        progress = self._copy_progress(task.progress)
        progress.playlist_failed_indexes = [item for item in progress.playlist_failed_indexes if item != playlist_index]
        failures = dict(progress.playlist_failures)
        failures.pop(str(playlist_index), None)
        progress.playlist_failures = failures
        progress.playlist_current_index = None
        progress.playlist_last_index = playlist_index - 1 if playlist_index > 1 else None
        progress.status_text = f"Retry queued for playlist item {playlist_index}"
        updated = self.storage.update_task(task_id, status="queued", progress=progress, error=None, finished_at=None)
        await self.queue.put(f"{task_id}:{playlist_index}")
        await self._publish("task_retry_queued", updated)
        return updated

    def list_tasks(self) -> list[TaskResponse]:
        return self.storage.list_tasks()

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
                if task.status == "cancelled":
                    continue
                if retry_index is None:
                    await self._run_task(task)
                else:
                    await self._retry_playlist_item(task, retry_index)
            finally:
                self.queue.task_done()

    async def _run_task(self, task: TaskResponse) -> None:
        request = CreateTaskRequest(**task.options)
        progress = task.progress
        output_tail, return_code, output_path, progress = await self._execute_download(task, request, progress)
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

    async def _retry_playlist_item(self, task: TaskResponse, playlist_index: int) -> None:
        entries = self._playlist_entries(task)
        entry = next((item for item in entries if item.index == playlist_index), None)
        if entry is None:
            return
        request = CreateTaskRequest(**task.options)
        request.playlist_items = str(playlist_index)
        request.playlist_entries = [entry]
        progress = self._copy_progress(task.progress)
        progress.playlist_current_index = playlist_index
        progress.playlist_last_index = playlist_index
        progress.percent = None
        progress.status_text = f"Retrying playlist item {playlist_index}"
        output_tail, return_code, output_path, progress = await self._execute_download(task, request, progress)
        if self.storage.get_task(task.id).status == "cancelled":
            return

        failed_indexes = [item for item in progress.playlist_failed_indexes if item != playlist_index]
        failures = dict(progress.playlist_failures)
        failures.pop(str(playlist_index), None)
        if return_code == 0:
            progress.playlist_failed_indexes = failed_indexes
            progress.playlist_failures = failures
            progress.playlist_current_index = None
            progress.playlist_last_index = max(progress.playlist_last_index or playlist_index, playlist_index)
            progress.percent = 100.0
            remaining_failures = bool(progress.playlist_failed_indexes)
            updated = self.storage.update_task(
                task.id,
                status="failed" if remaining_failures else "completed",
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

    async def _execute_download(self, task: TaskResponse, request: CreateTaskRequest, progress: TaskProgress) -> tuple[list[str], int, str | None, TaskProgress]:
        if not request.cookie_file:
            cookie_file = cookie_file_for_url(self.config.config_dir, request.url)
            if cookie_file is not None:
                request.cookie_file = str(cookie_file)
        before = snapshot_files(self.config.download_dir)
        started = self.storage.update_task(task.id, status="running", progress=progress, started_at=utc_now())
        await self._publish("task_started", started)

        cmd = build_download_command(request, self.config.download_dir)
        process_kwargs: dict[str, Any] = {}
        process_env = os.environ.copy()
        process_env.setdefault("PYTHONIOENCODING", "utf-8")
        process_env.setdefault("PYTHONUTF8", "1")
        process_env.setdefault("LANG", "C.UTF-8")
        if os.name == "nt":
            process_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            process_kwargs["preexec_fn"] = os.setsid

        output_tail: list[str] = []
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=process_env,
                **process_kwargs,
            )
        except FileNotFoundError:
            output_tail.append("yt-dlp is not installed")
            return output_tail, 127, None, progress
        except Exception as exc:
            output_tail.append(str(exc))
            return output_tail, 1, None, progress

        self.processes[task.id] = process
        try:
            assert process.stdout is not None
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = _decode_output_line(raw).strip()
                if line:
                    output_tail.append(line)
                    output_tail = output_tail[-20:]
                    progress = parse_progress_line(line, progress)
                    updated = self.storage.update_task(task.id, progress=progress)
                    await self._publish("task_progress", updated)
            return_code = await process.wait()
        finally:
            self.processes.pop(task.id, None)

        new_files = discover_new_files(self.config.download_dir, before)
        output_path = self._select_output_file(new_files, request) or progress.current_filename
        return output_tail, return_code, output_path, progress

    def _select_output_file(self, files: list[Path], request: CreateTaskRequest) -> str | None:
        if not files:
            return None
        expected_suffix = f".{request.audio_format if request.mode == 'audio' else request.output_format}".lower()
        matching_files = [path for path in files if path.suffix.lower() == expected_suffix]
        selected = matching_files[0] if matching_files else files[0]
        return str(selected)

    def _parse_queue_item(self, queue_item: str) -> tuple[str, int | None]:
        task_id, separator, retry_index_text = queue_item.partition(":")
        if not separator:
            return task_id, None
        try:
            return task_id, int(retry_index_text)
        except ValueError:
            return task_id, None

    def _playlist_entries(self, task: TaskResponse) -> list[PlaylistEntry]:
        raw_entries = task.options.get("playlist_entries", [])
        if not isinstance(raw_entries, list):
            return []
        return [PlaylistEntry(**entry) for entry in raw_entries if isinstance(entry, dict) and isinstance(entry.get("index"), int)]

    def _copy_progress(self, progress: TaskProgress) -> TaskProgress:
        data = progress.model_dump() if hasattr(progress, "model_dump") else progress.dict()
        return TaskProgress(**data)

    def _add_history_if_available(self, task: TaskResponse, output_path: str | None) -> None:
        if not output_path:
            return
        path = Path(output_path)
        if not path.exists():
            return
        self.storage.add_history(
            HistoryEntry(
                id=uuid.uuid4().hex,
                task_id=task.id,
                url=task.url,
                title=path.stem,
                output_path=str(path),
                file_size=path.stat().st_size,
                media_type=classify_file(path),
                status="completed",
                downloaded_at=utc_now(),
                metadata={"mode": task.mode},
            )
        )

    def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

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
