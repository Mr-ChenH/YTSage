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
from ..models import CreateTaskRequest, HistoryEntry, TaskEvent, TaskProgress, TaskResponse
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
            task_id = await self.queue.get()
            try:
                task = self.storage.get_task(task_id)
            except KeyError:
                self.queue.task_done()
                continue
            try:
                if task.status == "cancelled":
                    continue
                await self._run_task(task)
            finally:
                self.queue.task_done()

    async def _run_task(self, task: TaskResponse) -> None:
        request = CreateTaskRequest(**task.options)
        if not request.cookie_file:
            cookie_file = cookie_file_for_url(self.config.config_dir, request.url)
            if cookie_file is not None:
                request.cookie_file = str(cookie_file)
        before = snapshot_files(self.config.download_dir)
        started = self.storage.update_task(task.id, status="running", started_at=utc_now())
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

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=process_env,
                **process_kwargs,
            )
        except FileNotFoundError as exc:
            failed = self.storage.update_task(task.id, status="failed", error="yt-dlp is not installed", finished_at=utc_now())
            await self._publish("task_failed", failed)
            return
        except Exception as exc:
            failed = self.storage.update_task(task.id, status="failed", error=str(exc), finished_at=utc_now())
            await self._publish("task_failed", failed)
            return

        self.processes[task.id] = process
        progress = task.progress
        output_tail: list[str] = []
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

        if self.storage.get_task(task.id).status == "cancelled":
            return

        has_playlist_failures = bool(progress.playlist_failed_indexes)
        if return_code == 0:
            new_files = discover_new_files(self.config.download_dir, before)
            output_path = str(new_files[0]) if new_files else progress.current_filename
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
            if output_path:
                path = Path(output_path)
                if path.exists():
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
            await self._publish("task_failed" if has_playlist_failures else "task_completed", completed)
        else:
            failed = self.storage.update_task(
                task.id,
                status="failed",
                error="\n".join(output_tail[-8:]) or f"yt-dlp exited with code {return_code}",
                finished_at=utc_now(),
            )
            await self._publish("task_failed", failed)

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
