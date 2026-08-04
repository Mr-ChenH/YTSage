"""Safe file library helpers for downloads."""

from __future__ import annotations

import base64
import mimetypes
import urllib.parse
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException, Request, status
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

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


def resolve_download_file(root: Path, file_id: str) -> Path:
    relative = decode_file_id(file_id)
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="File is outside downloads root") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return candidate


def resolve_download_folder(root: Path, folder: str | None) -> tuple[Path, str]:
    root = root.resolve()
    folder_filter = _safe_folder_filter(folder)
    candidate = (root / folder_filter).resolve() if folder_filter else root
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Folder is outside downloads root") from exc
    if not candidate.is_dir():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Folder not found")
    archive_name = candidate.name if folder_filter else root.name
    return candidate, archive_name or "downloads"


def _safe_folder_filter(folder: str | None) -> str | None:
    if not folder:
        return None
    normalized = folder.replace("\\", "/").strip("/")
    if not normalized or normalized == ".":
        return None
    parts = Path(normalized).parts
    if any(part in {"..", ""} for part in parts):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid folder filter")
    return Path(*parts).as_posix()


def _file_entry(root: Path, request: Request, path: Path, stat) -> FileEntry:
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


def list_files(root: Path, request: Request, query: str | None = None, folder: str | None = None, offset: int = 0, limit: int = 50) -> FileListResponse:
    root = root.resolve()
    matched: list[tuple[Path, object]] = []
    folders: set[str] = set()
    query_lower = query.lower().strip() if query else None
    folder_filter = _safe_folder_filter(folder)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith(".ytsage-"):
            continue
        rel = path.relative_to(root).as_posix()
        parent = Path(rel).parent.as_posix()
        if parent == ".":
            parent = ""
        if parent:
            folders.add(parent)
        if folder_filter and parent != folder_filter and not parent.startswith(f"{folder_filter}/"):
            continue
        if query_lower and query_lower not in path.name.lower():
            continue
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        matched.append((path, stat))

    total = len(matched)
    page = matched[offset : offset + limit]
    files = [_file_entry(root, request, path, stat) for path, stat in page]
    return FileListResponse(
        root=str(root),
        files=files,
        folders=sorted(folders),
        total=total,
        offset=offset,
        limit=limit,
        query=query,
        folder=folder_filter,
    )


def download_response(path: Path) -> FileResponse:
    return FileResponse(path, filename=path.name, media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream")


class _ZipStream:
    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self._position = 0

    def write(self, data: bytes) -> int:
        self._chunks.append(data)
        self._position += len(data)
        return len(data)

    def tell(self) -> int:
        return self._position

    def seekable(self) -> bool:
        return False

    def writable(self) -> bool:
        return True

    def flush(self) -> None:
        return None

    def drain(self) -> bytes:
        data = b"".join(self._chunks)
        self._chunks.clear()
        return data


def _folder_files(folder: Path) -> Iterator[Path]:
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name.startswith(".ytsage-"):
            continue
        yield path


def _folder_zip_iterator(folder: Path, archive_name: str) -> Iterator[bytes]:
    stream = _ZipStream()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in _folder_files(folder):
            arcname = Path(archive_name) / path.relative_to(folder)
            archive.write(path, arcname.as_posix())
            chunk = stream.drain()
            if chunk:
                yield chunk
    chunk = stream.drain()
    if chunk:
        yield chunk


def folder_download_response(folder: Path, archive_name: str) -> StreamingResponse:
    filename = f"{archive_name}.zip"
    quoted_filename = urllib.parse.quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"}
    return StreamingResponse(_folder_zip_iterator(folder, archive_name), media_type="application/zip", headers=headers)


def folder_manifest_response(root: Path, folder: Path, archive_name: str, request: Request, manifest_format: str = "aria2") -> PlainTextResponse:
    manifest_format = manifest_format.lower()
    if manifest_format not in {"aria2", "txt", "json"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported manifest format")

    entries: list[dict[str, str]] = []
    for path in _folder_files(folder):
        rel = path.relative_to(root.resolve()).as_posix()
        file_id = encode_file_id(rel)
        url = str(request.base_url.replace(path=f"api/files/{file_id}/download", query=""))
        output = path.relative_to(folder).as_posix()
        entries.append({"url": url, "output": output})

    if manifest_format == "json":
        import json

        content = json.dumps(entries, ensure_ascii=False, indent=2)
        media_type = "application/json; charset=utf-8"
        extension = "json"
    elif manifest_format == "txt":
        content = "\n".join(entry["url"] for entry in entries) + ("\n" if entries else "")
        media_type = "text/plain; charset=utf-8"
        extension = "txt"
    else:
        content = "\n".join(f'{entry["url"]}\n  out={entry["output"]}' for entry in entries) + ("\n" if entries else "")
        media_type = "text/plain; charset=utf-8"
        extension = "aria2.txt"

    filename = f"{archive_name}.{extension}"
    quoted_filename = urllib.parse.quote(filename)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"}
    return PlainTextResponse(content, media_type=media_type, headers=headers)


def _file_iterator(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def stream_response(path: Path, range_header: str | None) -> StreamingResponse:
    size = path.stat().st_size
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not range_header:
        headers = {"Accept-Ranges": "bytes", "Content-Length": str(size)}
        return StreamingResponse(_file_iterator(path, 0, size - 1), media_type=media_type, headers=headers)

    if not range_header.startswith("bytes="):
        raise HTTPException(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE, detail="Invalid Range header")

    range_value = range_header.removeprefix("bytes=").split(",", 1)[0].strip()
    start_text, _, end_text = range_value.partition("-")
    try:
        if start_text:
            start = int(start_text)
            end = int(end_text) if end_text else size - 1
        else:
            suffix_length = int(end_text)
            start = max(size - suffix_length, 0)
            end = size - 1
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE, detail="Invalid Range header") from exc

    if start < 0 or end >= size or start > end:
        raise HTTPException(status_code=status.HTTP_416_RANGE_NOT_SATISFIABLE, detail="Requested range not satisfiable")

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{size}",
        "Content-Length": str(end - start + 1),
    }
    return StreamingResponse(_file_iterator(path, start, end), status_code=206, media_type=media_type, headers=headers)
