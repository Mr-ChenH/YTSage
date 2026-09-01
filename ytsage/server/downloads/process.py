from __future__ import annotations

import locale
import os
import signal
from pathlib import Path

from ..models import CreateTaskRequest


def decode_output_line(raw: bytes) -> str:
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


def select_output_file(files: list[Path], request: CreateTaskRequest) -> str | None:
    if not files:
        return None
    expected_suffix = f".{request.audio_format if request.mode == 'audio' else request.output_format}".lower()
    matching_files = [path for path in files if path.suffix.lower() == expected_suffix]
    return str(matching_files[0] if matching_files else files[0])


def terminate_process(process) -> None:
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
