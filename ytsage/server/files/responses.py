from __future__ import annotations

import mimetypes
import urllib.parse
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException, status
from fastapi.responses import StreamingResponse


def file_iterator(path: Path, start: int, end: int, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    with path.open("rb") as file:
        file.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


def range_response(path: Path, range_header: str | None, extra_headers: dict[str, str] | None = None) -> StreamingResponse:
    size = path.stat().st_size
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    base_headers = {"Accept-Ranges": "bytes", **(extra_headers or {})}
    if not range_header:
        return StreamingResponse(file_iterator(path, 0, size - 1), media_type=media_type, headers={**base_headers, "Content-Length": str(size)})
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

    headers = {**base_headers, "Content-Range": f"bytes {start}-{end}/{size}", "Content-Length": str(end - start + 1)}
    return StreamingResponse(file_iterator(path, start, end), status_code=206, media_type=media_type, headers=headers)


def ranged_download_response(path: Path, range_header: str | None) -> StreamingResponse:
    filename = urllib.parse.quote(path.name)
    return range_response(path, range_header, {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"})


def stream_response(path: Path, range_header: str | None) -> StreamingResponse:
    return range_response(path, range_header)
