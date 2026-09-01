from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Awaitable, Callable

from ..config import ServerConfig
from ..models import CreateTaskRequest, TaskProgress, TaskResponse
from ..services.cookies import cookie_file_for_url
from ..services.download_service import build_download_command, discover_new_files, parse_progress_line, snapshot_files
from ..services.storage import Storage, utc_now
from .process import decode_output_line, select_output_file

PublishCallback = Callable[[str, TaskResponse], Awaitable[None]]


class DownloadExecutor:
    """Runs yt-dlp processes and owns transport-level fallback behavior."""

    def __init__(self, config: ServerConfig, storage: Storage, processes: dict[str, asyncio.subprocess.Process], publish: PublishCallback) -> None:
        self.config = config
        self.storage = storage
        self.processes = processes
        self.publish = publish

    async def execute_with_youtube_fallback(self, task: TaskResponse, request: CreateTaskRequest, progress: TaskProgress, fallback_status: str = "Downloaded at 360p after YouTube rejected the selected format") -> tuple[list[str], int, str | None, TaskProgress]:
        output, return_code, output_path, progress = await self.execute(task, request, progress)
        error = next((line for line in reversed(output) if "ERROR:" in line), None)
        if return_code == 0 or not error or "HTTP Error 403" not in error or "youtube.com" not in request.url:
            return output, return_code, output_path, progress

        fallback_request = request.model_copy(deep=True)
        fallback_request.format_id = "18"
        fallback_request.cookie_file = None
        progress.status_text = "YouTube blocked the selected format; retrying at 360p"
        fallback_output, fallback_code, fallback_path, progress = await self.execute(task, fallback_request, progress, use_cookies=False)
        output.extend(fallback_output)
        if fallback_code == 0:
            progress.status_text = fallback_status
            return output, 0, fallback_path, progress
        return output, fallback_code, fallback_path, progress

    async def execute(self, task: TaskResponse, request: CreateTaskRequest, progress: TaskProgress, *, use_cookies: bool = True) -> tuple[list[str], int, str | None, TaskProgress]:
        if use_cookies and not request.cookie_file:
            cookie_file = cookie_file_for_url(self.config.config_dir, request.url)
            if cookie_file is not None:
                request.cookie_file = str(cookie_file)
        before = snapshot_files(self.config.download_dir)
        started = self.storage.update_task(task.id, status="running", progress=progress, started_at=utc_now())
        await self.publish("task_started", started)

        cmd = build_download_command(request, self.config.download_dir, single_item_directory=not bool(task.options.get("playlist_entries")))
        process_kwargs: dict[str, object] = {}
        process_env = os.environ.copy()
        process_env.setdefault("PYTHONIOENCODING", "utf-8")
        process_env.setdefault("PYTHONUTF8", "1")
        process_env.setdefault("LANG", "C.UTF-8")
        if os.name == "nt":
            process_kwargs["creationflags"] = getattr(__import__("subprocess"), "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            process_kwargs["preexec_fn"] = os.setsid

        output_tail: list[str] = []
        try:
            process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, env=process_env, **process_kwargs)
        except FileNotFoundError:
            return ["yt-dlp is not installed"], 127, None, progress
        except Exception as exc:
            return [str(exc)], 1, None, progress

        self.processes[task.id] = process
        try:
            assert process.stdout is not None
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = decode_output_line(raw).strip()
                if line:
                    output_tail = [*output_tail, line][-20:]
                    progress = parse_progress_line(line, progress)
                    await self.publish("task_progress", self.storage.update_task(task.id, progress=progress))
            return_code = await process.wait()
        finally:
            self.processes.pop(task.id, None)

        new_files = discover_new_files(self.config.download_dir, before)
        output_path = select_output_file(new_files, request) or progress.current_filename
        return output_tail, return_code, output_path, progress
