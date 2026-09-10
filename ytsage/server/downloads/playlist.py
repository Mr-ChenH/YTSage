from __future__ import annotations

import re
from typing import Any

from ..models import PlaylistEntry, TaskProgress, TaskResponse


def _safe_directory_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned[:120] or "Untitled"


def playlist_item_filename_template(template: str, title: str, index: int) -> str:
    result = template.replace("%(playlist_title)s", _safe_directory_name(title)).replace("%(playlist_index)s", str(index))
    return re.sub(r"%\(playlist_index\)0?\d*d", lambda match: format(index, match.group(0).split(")", 1)[1][:-1] or "d"), result)


def playlist_entry_filename_template(template: str, title: str, entry: PlaylistEntry) -> str:
    result = playlist_item_filename_template(template, title, entry.index)
    folders = [_safe_directory_name(group.title) for group in entry.group_path]
    if not folders:
        return result
    separator_index = max(result.rfind("/"), result.rfind("\\"))
    directory = result[:separator_index] if separator_index >= 0 else ""
    filename = result[separator_index + 1:] if separator_index >= 0 else result
    return "/".join([part for part in [directory, *folders, filename] if part])


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
