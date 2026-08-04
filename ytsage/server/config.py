"""Server runtime configuration for YTSage."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _path_from_env(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


def _int_from_env(name: str, default: int, minimum: int = 1, maximum: int = 8) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


@dataclass(frozen=True)
class ServerConfig:
    host: str
    port: int
    config_dir: Path
    download_dir: Path
    queue_concurrency: int
    auth_token: str | None
    static_dir: Path

    @property
    def database_path(self) -> Path:
        return self.config_dir / "ytsage_server.db"

    @property
    def cookie_file_path(self) -> Path:
        return self.cookie_file_for_profile("default")

    def cookie_file_for_profile(self, profile: str) -> Path:
        if profile == "default":
            return self.config_dir / "cookies.txt"
        return self.config_dir / f"cookies-{profile}.txt"


def load_config() -> ServerConfig:
    package_dir = Path(__file__).resolve().parent
    config = ServerConfig(
        host=os.environ.get("YTSAGE_HOST", "0.0.0.0"),
        port=_int_from_env("YTSAGE_PORT", 8080, minimum=1, maximum=65535),
        config_dir=_path_from_env("YTSAGE_CONFIG_DIR", "/config"),
        download_dir=_path_from_env("YTSAGE_DOWNLOAD_DIR", "/downloads"),
        queue_concurrency=_int_from_env("YTSAGE_QUEUE_CONCURRENCY", 2, minimum=1, maximum=8),
        auth_token=os.environ.get("YTSAGE_AUTH_TOKEN") or None,
        static_dir=package_dir / "static",
    )
    config.config_dir.mkdir(parents=True, exist_ok=True)
    config.download_dir.mkdir(parents=True, exist_ok=True)
    return config
