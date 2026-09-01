from __future__ import annotations

import re
from typing import Any

from ..models import PlaylistEntry, TaskProgress, TaskResponse


def playlist_item_filename_template(template: str, title: str, index: int) -> str:
    result = template.replace("%(playlist_title)s", title).replace("%(playlist_index)s", str(index))
    return re.sub(r"%\(playlist_index\)0?\d*d", lambda match: format(index, match.group(0).split(")", 1)[1][:-1] or "d"), result)


def playlist_entries(task: TaskResponse) -> list[PlaylistEntry]:
    raw_entries = task.options.get("playlist_entries", [])
    if not isinstance(raw_entries, list):
        return []
    return [PlaylistEntry(**entry) for entry in raw_entries if isinstance(entry, dict) and isinstance(entry.get("index"), int)]


def copy_progress(progress: TaskProgress) -> TaskProgress:
    data: dict[str, Any] = progress.model_dump() if hasattr(progress, "model_dump") else progress.dict()
    return TaskProgress(**data)


def parse_queue_item(queue_item: str) -> tuple[str, int | None]:
    task_id, separator, retry_index_text = queue_item.partition(":")
    if not separator:
        return task_id, None
    try:
        return task_id, int(retry_index_text)
    except ValueError:
        return task_id, None
