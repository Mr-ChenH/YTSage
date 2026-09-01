from __future__ import annotations

import base64
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, Request, status

from ..models import FileEntry, FileListResponse, MediaType

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".avi"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav"}
SUBTITLE_EXTENSIONS = {".vtt", ".srt", ".ass", ".ssa"}
PLAYABLE_EXTENSIONS = {".mp4", ".webm", ".mp3", ".m4a", ".ogg", ".opus", ".wav"}


def classify_file(path: Path) -> MediaType:
    suffix = path.suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in SUBTITLE_EXTENSIONS:
        return "subtitle"
    return "other"


def encode_file_id(relative_path: str) -> str:
    return base64.urlsafe_b64encode(relative_path.encode("utf-8")).decode("ascii").rstrip("=")


def decode_file_id(file_id: str) -> str:
    padding = "=" * (-len(file_id) % 4)
    try:
        return base64.urlsafe_b64decode((file_id + padding).encode("ascii")).decode("utf-8")
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file id") from exc


def safe_folder_filter(folder: str | None) -> str | None:
    if not folder:
        return None
    normalized = folder.replace("\\", "/").strip("/")
    if not normalized or normalized == ".":
        return None
    parts = Path(normalized).parts
    if any(part in {"..", ""} for part in parts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid folder filter")
    return Path(*parts).as_posix()


def resolve_download_file(root: Path, file_id: str) -> Path:
    candidate = (root / decode_file_id(file_id)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="File is outside downloads root") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return candidate


def resolve_download_folder(root: Path, folder: str | None) -> tuple[Path, str]:
    root = root.resolve()
    folder_filter = safe_folder_filter(folder)
    candidate = (root / folder_filter).resolve() if folder_filter else root
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Folder is outside downloads root") from exc
    if not candidate.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    archive_name = candidate.name if folder_filter else root.name
    return candidate, archive_name or "downloads"


def _file_entry(root: Path, request: Request, path: Path, stat: object) -> FileEntry:
    rel = path.relative_to(root).as_posix()
    file_id = encode_file_id(rel)
    media_type = classify_file(path)
    playable = path.suffix.lower() in PLAYABLE_EXTENSIONS
    return FileEntry(
        id=file_id,
        name=path.name,
        relative_path=rel,
        size=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        media_type=media_type,
        playable=playable,
        download_url=str(request.url_for("download_file", file_id=file_id)),
        stream_url=str(request.url_for("stream_file", file_id=file_id)) if playable else None,
    )


def list_files(root: Path, request: Request, query: str | None = None, folder: str | None = None, offset: int = 0, limit: int = 50, media_only: bool = False, direct_only: bool = False) -> FileListResponse:
    root = root.resolve()
    matched: list[tuple[Path, object]] = []
    folders: set[str] = set()
    query_lower = query.lower().strip() if query else None
    folder_filter = safe_folder_filter(folder)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith(".ytsage-"):
            continue
        rel = path.relative_to(root).as_posix()
        parent = Path(rel).parent.as_posix()
        if parent == ".":
            parent = ""
        if parent:
            folders.add(parent)
        if folder_filter:
            if direct_only and parent != folder_filter:
                continue
            if not direct_only and parent != folder_filter and not parent.startswith(f"{folder_filter}/"):
                continue
        elif direct_only and parent:
            continue
        if media_only and path.suffix.lower() not in PLAYABLE_EXTENSIONS:
            continue
        if query_lower and query_lower not in path.name.lower():
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        matched.append((path, stat))

    page = matched[offset : offset + limit]
    return FileListResponse(
        root=str(root),
        files=[_file_entry(root, request, path, stat) for path, stat in page],
        folders=sorted(folders),
        total=len(matched),
        offset=offset,
        limit=limit,
        query=query,
        folder=folder_filter,
    )


def delete_download_file(root: Path, file_id: str) -> None:
    path = resolve_download_file(root, file_id)
    path.unlink()
    _remove_empty_parents(path.parent, root.resolve())


def delete_download_folder(root: Path, folder: str) -> None:
    root = root.resolve()
    folder_filter = safe_folder_filter(folder)
    if not folder_filter:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Downloads root cannot be deleted")
    candidate = (root / folder_filter).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Folder is outside downloads root") from exc
    if candidate == root:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Downloads root cannot be deleted")
    if not candidate.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    shutil.rmtree(candidate)
    _remove_empty_parents(candidate.parent, root)


def _remove_empty_parents(path: Path, root: Path) -> None:
    while path != root:
        try:
            path.rmdir()
        except OSError:
            break
        path = path.parent
