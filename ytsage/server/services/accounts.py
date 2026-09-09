"""Platform account credential and library management."""

from __future__ import annotations

import os
import shutil
import sqlite3
import uuid
from pathlib import Path

from ..models import AccountCreateRequest, AccountResponse, AccountResourceEntriesResponse, AccountResourceListResponse, AccountUpdateRequest, PlatformAccount
from ..providers.bilibili import BilibiliProvider, BilibiliProviderError
from .cookies import cookie_profile_status, normalize_cookies
from .storage import Storage, utc_now


class AccountConflictError(ValueError):
    pass


class AccountService:
    def __init__(self, config_dir: Path, storage: Storage, bilibili: BilibiliProvider | None = None) -> None:
        self.config_dir = config_dir
        self.storage = storage
        self.accounts_dir = config_dir / "accounts"
        self.bilibili = bilibili or BilibiliProvider()

    def create(self, request: AccountCreateRequest) -> AccountResponse:
        normalized = normalize_cookies(request.cookie_content)
        if normalized is None:
            raise ValueError("Cookie data is required.")
        account_id = uuid.uuid4().hex
        directory = self.accounts_dir / account_id
        directory.mkdir(parents=True, exist_ok=False)
        temporary = directory / "cookies.tmp"
        target = directory / "cookies.txt"
        try:
            self._write_cookie_file(temporary, normalized)
            identity = self.bilibili.verify(temporary)
            duplicate = next((item for item in self.storage.list_accounts(request.platform) if item.external_id == identity.external_id), None)
            if duplicate:
                raise AccountConflictError("This Bilibili identity is already configured.")
            make_default = request.make_default or not self.storage.list_accounts(request.platform)
            account = self.storage.create_account(account_id, request.platform, request.label.strip(), f"accounts/{account_id}/cookies.txt", make_default)
            temporary.replace(target)
            account = self.storage.update_account(
                account.id, external_id=identity.external_id, display_name=identity.display_name,
                avatar_url=identity.avatar_url, vip_type=identity.vip_type, state="valid",
                last_verified_at=utc_now(), last_error=None,
            )
            return self.response(account)
        except sqlite3.IntegrityError as exc:
            shutil.rmtree(directory, ignore_errors=True)
            raise AccountConflictError("An account with this label already exists.") from exc
        except Exception:
            if not target.exists():
                shutil.rmtree(directory, ignore_errors=True)
            else:
                try:
                    self.storage.delete_account(account_id)
                except KeyError:
                    pass
                shutil.rmtree(directory, ignore_errors=True)
            raise

    def list(self, platform: str | None = None) -> list[AccountResponse]:
        return [self.response(account) for account in self.storage.list_accounts(platform)]

    def get(self, account_id: str) -> AccountResponse:
        return self.response(self.storage.get_account(account_id))

    def update(self, account_id: str, request: AccountUpdateRequest) -> AccountResponse:
        account = self.storage.get_account(account_id)
        fields: dict[str, object] = {}
        if request.label is not None:
            normalized_label = request.label.strip()
            duplicate_label = next((item for item in self.storage.list_accounts(account.platform) if item.id != account.id and item.label == normalized_label), None)
            if duplicate_label:
                raise AccountConflictError("An account with this label already exists.")
            fields["label"] = normalized_label
        if request.make_default is not None:
            fields["is_default"] = request.make_default
        if request.cookie_content is not None:
            normalized = normalize_cookies(request.cookie_content)
            if normalized is None:
                raise ValueError("Cookie data is required.")
            target = self.resolve_cookie_file(account_id, account.platform, require_usable=False)
            temporary = target.with_suffix(".tmp")
            self._write_cookie_file(temporary, normalized)
            try:
                identity = self.bilibili.verify(temporary)
                duplicate = next((item for item in self.storage.list_accounts(account.platform) if item.id != account.id and item.external_id == identity.external_id), None)
                if duplicate:
                    raise AccountConflictError("This Bilibili identity is already configured.")
                temporary.replace(target)
                fields.update(external_id=identity.external_id, display_name=identity.display_name, avatar_url=identity.avatar_url, vip_type=identity.vip_type, state="valid", last_verified_at=utc_now(), last_error=None)
            finally:
                temporary.unlink(missing_ok=True)
        try:
            return self.response(self.storage.update_account(account_id, **fields))
        except sqlite3.IntegrityError as exc:
            raise AccountConflictError("An account with this label already exists.") from exc

    def verify(self, account_id: str) -> AccountResponse:
        account = self.storage.get_account(account_id)
        cookie_file = self.resolve_cookie_file(account_id, account.platform, require_usable=False)
        status = cookie_profile_status(cookie_file)
        if not status.usable:
            state = "expired" if status.state == "expired" else "invalid"
            return self.response(self.storage.update_account(account_id, state=state, last_verified_at=utc_now(), last_error="Cookie data is expired or invalid."))
        try:
            identity = self.bilibili.verify(cookie_file)
        except BilibiliProviderError as exc:
            state = "invalid" if exc.code == "account_login_invalid" else "unknown"
            self.storage.update_account(account_id, state=state, last_verified_at=utc_now(), last_error=str(exc))
            raise
        duplicate = next((item for item in self.storage.list_accounts(account.platform) if item.id != account.id and item.external_id == identity.external_id), None)
        if duplicate:
            raise AccountConflictError("This Bilibili identity is already configured.")
        return self.response(self.storage.update_account(
            account_id, external_id=identity.external_id, display_name=identity.display_name,
            avatar_url=identity.avatar_url, vip_type=identity.vip_type, state="valid",
            last_verified_at=utc_now(), last_error=None,
        ))

    def delete(self, account_id: str) -> None:
        account = self.storage.get_account(account_id)
        if self.storage.count_account_monitors(account_id):
            raise AccountConflictError("Delete or reassign this account's monitors first.")
        if self.storage.count_account_active_tasks(account_id):
            raise AccountConflictError("Wait for or cancel this account's active downloads first.")
        directory = self.resolve_cookie_file(account_id, account.platform, require_usable=False).parent
        self.storage.delete_account(account_id)
        shutil.rmtree(directory, ignore_errors=True)
        if account.is_default:
            remaining = self.storage.list_accounts(account.platform)
            if remaining:
                self.storage.update_account(remaining[0].id, is_default=True)

    def resolve_cookie_file(self, account_id: str, expected_platform: str | None = None, *, require_usable: bool = True) -> Path:
        account = self.storage.get_account(account_id)
        if expected_platform and account.platform != expected_platform:
            raise AccountConflictError("The selected account does not match this platform.")
        root = self.accounts_dir.resolve()
        path = (self.config_dir / account.cookie_filename).resolve()
        if root not in path.parents:
            raise AccountConflictError("The account credential path is invalid.")
        status = cookie_profile_status(path)
        if require_usable and not status.usable:
            raise AccountConflictError("The selected account credentials are expired or invalid.")
        return path

    def list_resources(self, account_id: str, kind: str, offset: int, limit: int) -> AccountResourceListResponse:
        account = self.storage.get_account(account_id)
        try:
            return self.bilibili.list_resources(account, self.resolve_cookie_file(account_id, "bilibili"), kind, offset, limit)
        except BilibiliProviderError as exc:
            if exc.code == "account_login_invalid":
                self.storage.update_account(account_id, state="invalid", last_verified_at=utc_now(), last_error=str(exc))
            raise

    def list_entries(self, account_id: str, resource_id: str, offset: int, limit: int) -> AccountResourceEntriesResponse:
        account = self.storage.get_account(account_id)
        try:
            return self.bilibili.list_entries(account, self.resolve_cookie_file(account_id, "bilibili"), resource_id, offset, limit)
        except BilibiliProviderError as exc:
            if exc.code == "account_login_invalid":
                self.storage.update_account(account_id, state="invalid", last_verified_at=utc_now(), last_error=str(exc))
            raise

    def response(self, account: PlatformAccount) -> AccountResponse:
        status = cookie_profile_status(self.resolve_cookie_file(account.id, account.platform, require_usable=False))
        return AccountResponse(
            id=account.id, platform=account.platform, label=account.label, external_id=account.external_id,
            display_name=account.display_name, avatar_url=account.avatar_url, vip_type=account.vip_type,
            state=account.state, cookie_status=status, is_default=account.is_default,
            last_verified_at=account.last_verified_at, last_error=account.last_error,
            created_at=account.created_at, updated_at=account.updated_at,
        )

    @staticmethod
    def _write_cookie_file(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
