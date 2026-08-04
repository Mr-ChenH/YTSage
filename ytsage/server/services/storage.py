"""SQLite storage for server tasks and history."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import CreateTaskRequest, HistoryEntry, TaskProgress, TaskResponse


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_to_dict(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    status TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    progress_json TEXT NOT NULL,
                    error TEXT,
                    output_path TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks (updated_at DESC)")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history (
                    id TEXT PRIMARY KEY,
                    task_id TEXT,
                    url TEXT,
                    title TEXT,
                    output_path TEXT,
                    file_size INTEGER,
                    media_type TEXT,
                    status TEXT,
                    downloaded_at TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_history_downloaded ON history (downloaded_at DESC)")

    def create_task(self, task_id: str, request: CreateTaskRequest) -> TaskResponse:
        now = utc_now()
        options = model_to_dict(request)
        progress = TaskProgress()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO tasks (id, url, mode, status, options_json, progress_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    request.url,
                    request.mode,
                    "queued",
                    json.dumps(options),
                    json.dumps(model_to_dict(progress)),
                    now,
                    now,
                ),
            )
        return self.get_task(task_id)

    def update_task(self, task_id: str, **fields: Any) -> TaskResponse:
        if not fields:
            return self.get_task(task_id)
        fields["updated_at"] = utc_now()
        values: list[Any] = []
        sets: list[str] = []
        for key, value in fields.items():
            column = key
            if key == "options":
                column = "options_json"
                value = json.dumps(value)
            elif key == "progress":
                column = "progress_json"
                value = json.dumps(model_to_dict(value) if not isinstance(value, dict) else value)
            sets.append(f"{column} = ?")
            values.append(value)
        values.append(task_id)
        with self._lock, self._conn:
            self._conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id = ?", values)
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> TaskResponse:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def list_tasks(self, limit: int = 100) -> list[TaskResponse]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._task_from_row(row) for row in rows]

    def delete_task(self, task_id: str) -> None:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        if cursor.rowcount == 0:
            raise KeyError(task_id)

    def clear_finished_tasks(self) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM tasks WHERE status NOT IN ('queued', 'running')")
        return int(cursor.rowcount)

    def mark_interrupted_tasks(self) -> None:
        now = utc_now()
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE tasks
                SET status = 'interrupted', updated_at = ?, finished_at = ?, error = COALESCE(error, 'Server restarted before task completed')
                WHERE status IN ('queued', 'running')
                """,
                (now, now),
            )

    def add_history(self, entry: HistoryEntry) -> None:
        data = model_to_dict(entry)
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO history (
                    id, task_id, url, title, output_path, file_size, media_type, status, downloaded_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.id,
                    entry.task_id,
                    entry.url,
                    entry.title,
                    entry.output_path,
                    entry.file_size,
                    entry.media_type,
                    entry.status,
                    entry.downloaded_at,
                    json.dumps(data.get("metadata", {})),
                ),
            )

    def list_history(self, limit: int = 100) -> list[HistoryEntry]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM history ORDER BY downloaded_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._history_from_row(row) for row in rows]

    def delete_history(self, history_id: str) -> None:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM history WHERE id = ?", (history_id,))
        if cursor.rowcount == 0:
            raise KeyError(history_id)

    def clear_history(self) -> int:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM history")
        return int(cursor.rowcount)

    def _task_from_row(self, row: sqlite3.Row) -> TaskResponse:
        return TaskResponse(
            id=row["id"],
            url=row["url"],
            mode=row["mode"],
            status=row["status"],
            options=json.loads(row["options_json"] or "{}"),
            progress=TaskProgress(**json.loads(row["progress_json"] or "{}")),
            error=row["error"],
            output_path=row["output_path"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

    def _history_from_row(self, row: sqlite3.Row) -> HistoryEntry:
        return HistoryEntry(
            id=row["id"],
            task_id=row["task_id"],
            url=row["url"],
            title=row["title"],
            output_path=row["output_path"],
            file_size=row["file_size"],
            media_type=row["media_type"] or "other",
            status=row["status"] or "completed",
            downloaded_at=row["downloaded_at"],
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
