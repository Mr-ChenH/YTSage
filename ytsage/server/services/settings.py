"""Persistent server preference helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_FILENAME_TEMPLATE = "%(title)s_%(resolution)s_[%(id)s].%(ext)s"
DEFAULT_VIDEO_RESOLUTION = "best"
SETTINGS_FILENAME = "server-settings.json"


def settings_path(config_dir: Path) -> Path:
    return config_dir / SETTINGS_FILENAME


def load_server_settings(config_dir: Path) -> dict[str, Any]:
    path = settings_path(config_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_server_settings(config_dir: Path, settings: dict[str, Any]) -> None:
    path = settings_path(config_dir)
    path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def filename_template(config_dir: Path) -> str:
    value = load_server_settings(config_dir).get("filename_template")
    return value if isinstance(value, str) and value.strip() else DEFAULT_FILENAME_TEMPLATE


def save_filename_template(config_dir: Path, template: str) -> str:
    normalized = template.strip()
    settings = load_server_settings(config_dir)
    settings["filename_template"] = normalized
    save_server_settings(config_dir, settings)
    return normalized


def default_video_resolution(config_dir: Path) -> str:
    value = load_server_settings(config_dir).get("default_video_resolution")
    return value if isinstance(value, str) and value.strip() else DEFAULT_VIDEO_RESOLUTION


def save_default_video_resolution(config_dir: Path, resolution: str) -> str:
    normalized = resolution.strip() or DEFAULT_VIDEO_RESOLUTION
    settings = load_server_settings(config_dir)
    settings["default_video_resolution"] = normalized
    save_server_settings(config_dir, settings)
    return normalized
