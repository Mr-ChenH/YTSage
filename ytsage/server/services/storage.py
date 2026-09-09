"""SQLite storage for server tasks and history."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..models import CreateTaskRequest, HistoryEntry, PlaylistMonitorCreate, PlaylistMonitorResponse, TaskProgress, TaskResponse


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
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS playlist_monitors (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    title TEXT,
                    enabled INTEGER NOT NULL,
                    interval_minutes INTEGER NOT NULL,
                    download_options_json TEXT NOT NULL,
                    seen_entry_keys_json TEXT NOT NULL,
                    last_checked_at TEXT,
                    next_check_at TEXT NOT NULL,
                    last_error TEXT,
                    last_task_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_playlist_monitors_due ON playlist_monitors (enabled, next_check_at)")

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

    def list_tasks(self, limit: int = 100, offset: int = 0, active_only: bool = False) -> list[TaskResponse]:
        query = "SELECT * FROM tasks"
        values: list[object] = []
        if active_only:
            query += " WHERE status IN ('queued', 'running')"
        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        values.extend([limit, offset])
        with self._lock:
            rows = self._conn.execute(query, values).fetchall()
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

    def recover_interrupted_tasks(self) -> list[TaskResponse]:
        """Requeue work left active by the previous server process."""
        now = utc_now()
        with self._lock, self._conn:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE status IN ('queued', 'running') ORDER BY created_at"
            ).fetchall()
            if not rows:
                return []
            task_ids = [row["id"] for row in rows]
            placeholders = ", ".join("?" for _ in task_ids)
            self._conn.execute(
                f"""
                UPDATE tasks
                SET status = 'queued', updated_at = ?, finished_at = NULL, error = NULL
                WHERE id IN ({placeholders})
                """,
                [now, *task_ids],
            )
            recovered_rows = self._conn.execute(
                f"SELECT * FROM tasks WHERE id IN ({placeholders}) ORDER BY created_at",
                task_ids,
            ).fetchall()
        return [self._task_from_row(row) for row in recovered_rows]

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

    def create_monitor(self, monitor_id: str, request: PlaylistMonitorCreate) -> PlaylistMonitorResponse:
        now = utc_now()
        options = model_to_dict(request.download_options)
        options["url"] = request.url
        with self._lock, self._conn:
            existing = self._conn.execute(
                "SELECT id FROM playlist_monitors WHERE url = ?",
                (request.url,),
            ).fetchone()
            if existing is not None:
                raise ValueError("This playlist is already monitored")
            self._conn.execute(
                """
                INSERT INTO playlist_monitors (
                    id, url, enabled, interval_minutes, download_options_json,
                    seen_entry_keys_json, next_check_at, created_at, updated_at
                ) VALUES (?, ?, 1, ?, ?, '[]', ?, ?, ?)
                """,
                (monitor_id, request.url, request.interval_minutes, json.dumps(options), now, now, now),
            )
        return self.get_monitor(monitor_id)

    def get_monitor(self, monitor_id: str) -> PlaylistMonitorResponse:
        with self._lock:
            row = self._conn.execute("SELECT * FROM playlist_monitors WHERE id = ?", (monitor_id,)).fetchone()
        if row is None:
            raise KeyError(monitor_id)
        return self._monitor_from_row(row)

    def list_monitors(self) -> list[PlaylistMonitorResponse]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM playlist_monitors ORDER BY created_at DESC").fetchall()
        return [self._monitor_from_row(row) for row in rows]

    def list_due_monitors(self, now: str | None = None) -> list[PlaylistMonitorResponse]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM playlist_monitors WHERE enabled = 1 AND next_check_at <= ? ORDER BY next_check_at",
                (now or utc_now(),),
            ).fetchall()
        return [self._monitor_from_row(row) for row in rows]

    def update_monitor(self, monitor_id: str, **fields: Any) -> PlaylistMonitorResponse:
        if not fields:
            return self.get_monitor(monitor_id)
        fields["updated_at"] = utc_now()
        sets: list[str] = []
        values: list[Any] = []
        for key, value in fields.items():
            if key == "download_options":
                key, value = "download_options_json", json.dumps(value)
            elif key == "seen_entry_keys":
                key, value = "seen_entry_keys_json", json.dumps(value)
            elif key == "enabled":
                value = int(value)
            sets.append(f"{key} = ?")
            values.append(value)
        values.append(monitor_id)
        with self._lock, self._conn:
            cursor = self._conn.execute(f"UPDATE playlist_monitors SET {', '.join(sets)} WHERE id = ?", values)
        if cursor.rowcount == 0:
            raise KeyError(monitor_id)
        return self.get_monitor(monitor_id)

    def schedule_next_monitor_check(self, monitor_id: str, interval_minutes: int, **fields: Any) -> PlaylistMonitorResponse:
        fields["next_check_at"] = (datetime.now(timezone.utc) + timedelta(minutes=interval_minutes)).isoformat()
        return self.update_monitor(monitor_id, **fields)

    def delete_monitor(self, monitor_id: str) -> None:
        with self._lock, self._conn:
            cursor = self._conn.execute("DELETE FROM playlist_monitors WHERE id = ?", (monitor_id,))
        if cursor.rowcount == 0:
            raise KeyError(monitor_id)

    def _monitor_from_row(self, row: sqlite3.Row) -> PlaylistMonitorResponse:
        return PlaylistMonitorResponse(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            enabled=bool(row["enabled"]),
            interval_minutes=row["interval_minutes"],
            download_options=json.loads(row["download_options_json"] or "{}"),
            seen_entry_keys=json.loads(row["seen_entry_keys_json"] or "[]"),
            last_checked_at=row["last_checked_at"],
            next_check_at=row["next_check_at"],
            last_error=row["last_error"],
            last_task_id=row["last_task_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
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

    def list_history(self, limit: int = 100, offset: int = 0) -> list[HistoryEntry]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM history ORDER BY downloaded_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        return [self._history_from_row(row) for row in rows]

    def search_history(
        self,
        limit: int = 20,
        offset: int = 0,
        query: str | None = None,
        status: str | None = None,
        media_type: str | None = None,
    ) -> tuple[list[HistoryEntry], int]:
        clauses: list[str] = []
        values: list[object] = []
        if query:
            clauses.append("(title LIKE ? OR url LIKE ? OR output_path LIKE ?)")
            pattern = f"%{query}%"
            values.extend([pattern, pattern, pattern])
        if status:
            clauses.append("status = ?")
            values.append(status)
        if media_type:
            clauses.append("media_type = ?")
            values.append(media_type)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._lock:
            total = int(self._conn.execute(f"SELECT COUNT(*) FROM history{where}", values).fetchone()[0])
            rows = self._conn.execute(
                f"SELECT * FROM history{where} ORDER BY downloaded_at DESC LIMIT ? OFFSET ?",
                [*values, limit, offset],
            ).fetchall()
        return [self._history_from_row(row) for row in rows], total

    def get_history(self, history_id: str) -> HistoryEntry:
        with self._lock:
            row = self._conn.execute("SELECT * FROM history WHERE id = ?", (history_id,)).fetchone()
        if row is None:
            raise KeyError(history_id)
        return self._history_from_row(row)

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
