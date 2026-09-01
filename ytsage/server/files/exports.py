from __future__ import annotations

import json
import urllib.parse
import zipfile
from pathlib import Path
from typing import Iterator

from fastapi import HTTPException, Request, status
from fastapi.responses import PlainTextResponse, StreamingResponse

from .catalog import encode_file_id


class ZipStream:
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


def folder_files(folder: Path) -> Iterator[Path]:
    for path in sorted(folder.rglob("*")):
        if path.is_file() and not path.name.startswith(".ytsage-"):
            yield path


def folder_zip_iterator(folder: Path, archive_name: str) -> Iterator[bytes]:
    stream = ZipStream()
    with zipfile.ZipFile(stream, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in folder_files(folder):
            archive.write(path, (Path(archive_name) / path.relative_to(folder)).as_posix())
            chunk = stream.drain()
            if chunk:
                yield chunk
    chunk = stream.drain()
    if chunk:
        yield chunk


def folder_download_response(folder: Path, archive_name: str) -> StreamingResponse:
    quoted_filename = urllib.parse.quote(f"{archive_name}.zip")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"}
    return StreamingResponse(folder_zip_iterator(folder, archive_name), media_type="application/zip", headers=headers)


def folder_manifest_response(root: Path, folder: Path, archive_name: str, request: Request, manifest_format: str = "aria2") -> PlainTextResponse:
    manifest_format = manifest_format.lower()
    if manifest_format not in {"aria2", "txt", "json"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported manifest format")

    entries: list[dict[str, str]] = []
    for path in folder_files(folder):
        file_id = encode_file_id(path.relative_to(root.resolve()).as_posix())
        entries.append({
            "url": str(request.base_url.replace(path=f"api/files/{file_id}/download", query="")),
            "output": path.relative_to(folder).as_posix(),
        })

    if manifest_format == "json":
        content = json.dumps(entries, ensure_ascii=False, indent=2)
        media_type, extension = "application/json; charset=utf-8", "json"
    elif manifest_format == "txt":
        content = "\n".join(entry["url"] for entry in entries) + ("\n" if entries else "")
        media_type, extension = "text/plain; charset=utf-8", "txt"
    else:
        content = "\n".join(f'{entry["url"]}\n  dir=.\n  out={entry["output"]}\n  split=8\n  max-connection-per-server=8\n  continue=true' for entry in entries) + ("\n" if entries else "")
        media_type, extension = "text/plain; charset=utf-8", "aria2.txt"

    quoted_filename = urllib.parse.quote(f"{archive_name}.{extension}")
    return PlainTextResponse(content, media_type=media_type, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"})
