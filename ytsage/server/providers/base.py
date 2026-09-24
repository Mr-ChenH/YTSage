"""Shared contracts for platform account providers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ProviderError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class PlatformIdentity:
    external_id: str
    display_name: str
    avatar_url: str | None = None
    vip_type: int | None = None


class AccountProvider(Protocol):
    platform: str
    cookie_domain: str
    allow_unverified_import: bool

    def validate_cookie_file(self, cookie_file: Path) -> None: ...

    def verify(self, cookie_file: Path) -> PlatformIdentity: ...
