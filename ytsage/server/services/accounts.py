"""Platform account credential and library management."""

from __future__ import annotations

import asyncio
import os
import shutil
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from http.cookiejar import MozillaCookieJar
from pathlib import Path

from ..models import AccountCreateRequest, AccountResponse, AccountResource, AccountResourceEntriesResponse, AccountResourceListResponse, AccountUpdateRequest, BilibiliQrPollResponse, BilibiliQrStartRequest, BilibiliQrStartResponse, PlatformAccount, PlaylistEntry
from ..providers.base import AccountProvider, PlatformIdentity, ProviderError
from ..providers.bilibili import BilibiliProvider, BilibiliProviderError, BilibiliQrSession
from ..providers.douyin import DouyinProvider
from .cookies import cookie_profile_status, normalize_cookies
from .storage import Storage, utc_now


class AccountConflictError(ValueError):
    pass


class AccountService:
    def __init__(
        self,
        config_dir: Path,
        storage: Storage,
        bilibili: BilibiliProvider | None = None,
        douyin: DouyinProvider | None = None,
        providers: dict[str, AccountProvider] | None = None,
    ) -> None:
        self.config_dir = config_dir
        self.storage = storage
        self.accounts_dir = config_dir / "accounts"
        self.bilibili = bilibili or BilibiliProvider()
        self.douyin = douyin or DouyinProvider()
        self.providers: dict[str, AccountProvider] = {
            "bilibili": self.bilibili,
            "douyin": self.douyin,
            **(providers or {}),
        }
        self._qr_challenges: dict[str, tuple[BilibiliQrSession, BilibiliQrStartRequest]] = {}
        self._refresh_locks: dict[str, threading.Lock] = {}
        self._resource_locks: dict[str, threading.Lock] = {}
        self._resource_locks_guard = threading.Lock()
        self._maintenance_runner: asyncio.Task[None] | None = None
        self._started = False

    async def start(self) -> None:
        await self._warm_douyin_accounts()
        self._started = True
        if self._maintenance_runner is None:
            self._maintenance_runner = asyncio.create_task(self._maintenance_loop())

    async def stop(self) -> None:
        self._started = False
        if self._maintenance_runner is not None:
            self._maintenance_runner.cancel()
            await asyncio.gather(self._maintenance_runner, return_exceptions=True)
            self._maintenance_runner = None
        for provider in self.providers.values():
            close = getattr(provider, "close", None)
            if close:
                close()

    def create(self, request: AccountCreateRequest) -> AccountResponse:
        provider = self._provider(request.platform)
        normalized = normalize_cookies(request.cookie_content, self._cookie_domain(provider, request.platform))
        if normalized is None:
            raise ValueError("Cookie data is required.")
        account_id = uuid.uuid4().hex
        directory = self.accounts_dir / account_id
        directory.mkdir(parents=True, exist_ok=False)
        temporary = directory / "cookies.tmp"
        target = directory / "cookies.txt"
        try:
            self._write_cookie_file(temporary, normalized)
            identity, state, verification_error = self._verify_import(provider, temporary)
            if identity is not None:
                self._ensure_identity_available(request.platform, identity.external_id)
            make_default = request.make_default or not self.storage.list_accounts(request.platform)
            account = self.storage.create_account(account_id, request.platform, request.label.strip(), f"accounts/{account_id}/cookies.txt", make_default)
            temporary.replace(target)
            fields: dict[str, object] = {
                "state": state,
                "login_method": "cookie",
                "auto_refresh": False,
                "last_refresh_error": None,
                "last_verified_at": utc_now(),
                "last_error": verification_error,
            }
            if identity is not None:
                fields.update(self._identity_fields(identity))
            account = self.storage.update_account(account.id, **fields)
            if self._started:
                self._warm_douyin_account(account)
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
            provider = self._provider(account.platform)
            normalized = normalize_cookies(request.cookie_content, self._cookie_domain(provider, account.platform))
            if normalized is None:
                raise ValueError("Cookie data is required.")
            target = self.resolve_cookie_file(account_id, account.platform, require_usable=False)
            temporary = target.with_suffix(".tmp")
            self._write_cookie_file(temporary, normalized)
            try:
                identity, state, verification_error = self._verify_import(provider, temporary)
                if identity is not None:
                    self._ensure_identity_available(account.platform, identity.external_id, exclude_account_id=account.id)
                temporary.replace(target)
                (target.parent / "refresh-token.txt").unlink(missing_ok=True)
                fields.update(
                    state=state,
                    login_method="cookie",
                    auto_refresh=False,
                    last_refresh_at=None,
                    last_refresh_check_at=None,
                    last_refresh_error=None,
                    last_verified_at=utc_now(),
                    last_error=verification_error,
                )
                if identity is not None:
                    fields.update(self._identity_fields(identity))
                else:
                    fields.update(external_id=None, display_name=None, avatar_url=None, vip_type=None)
            finally:
                temporary.unlink(missing_ok=True)
        try:
            updated = self.storage.update_account(account_id, **fields)
            if self._started and request.cookie_content is not None:
                self._warm_douyin_account(updated)
            return self.response(updated)
        except sqlite3.IntegrityError as exc:
            raise AccountConflictError("An account with this label already exists.") from exc

    def verify(self, account_id: str) -> AccountResponse:
        account = self.storage.get_account(account_id)
        provider = self._provider(account.platform)
        cookie_file = self.resolve_cookie_file(account_id, account.platform, require_usable=False)
        status = cookie_profile_status(cookie_file)
        if not status.usable:
            state = "expired" if status.state == "expired" else "invalid"
            return self.response(self.storage.update_account(account_id, state=state, last_verified_at=utc_now(), last_error="Cookie data is expired or invalid."))
        try:
            if hasattr(provider, "validate_cookie_file"):
                provider.validate_cookie_file(cookie_file)
            identity = provider.verify(cookie_file)
        except ProviderError as exc:
            if getattr(provider, "allow_unverified_import", False) and exc.code != "account_login_invalid":
                return self.response(self.storage.update_account(
                    account_id, state="unknown", last_verified_at=utc_now(), last_error=str(exc),
                ))
            state = "invalid" if exc.code == "account_login_invalid" else "unknown"
            self.storage.update_account(account_id, state=state, last_verified_at=utc_now(), last_error=str(exc))
            raise
        self._ensure_identity_available(account.platform, identity.external_id, exclude_account_id=account.id)
        return self.response(self.storage.update_account(
            account_id, **self._identity_fields(identity), state="valid",
            last_verified_at=utc_now(), last_error=None,
        ))

    def start_qr_login(self, request: BilibiliQrStartRequest) -> BilibiliQrStartResponse:
        if request.account_id is not None:
            account = self.storage.get_account(request.account_id)
            if account.platform != "bilibili":
                raise AccountConflictError("The selected account is not a Bilibili account.")
        now = time.time()
        self._qr_challenges = {
            key: value for key, value in self._qr_challenges.items()
            if value[0].expires_at > now
        }
        challenge = self.bilibili.start_qr_login()
        challenge_id = uuid.uuid4().hex
        self._qr_challenges[challenge_id] = (challenge, request)
        return BilibiliQrStartResponse(
            challenge_id=challenge_id,
            qr_url=challenge.qr_url,
            expires_at=datetime.fromtimestamp(challenge.expires_at, timezone.utc).isoformat(),
        )

    def poll_qr_login(self, challenge_id: str) -> BilibiliQrPollResponse:
        item = self._qr_challenges.get(challenge_id)
        if item is None:
            raise KeyError(challenge_id)
        challenge, request = item
        result = self.bilibili.poll_qr_login(challenge)
        if result.status == "expired":
            self._qr_challenges.pop(challenge_id, None)
        if result.status != "completed" or result.cookies is None or result.refresh_token is None:
            return BilibiliQrPollResponse(status=result.status, message=result.message)
        try:
            account = (
                self._replace_from_qr(request.account_id, result.cookies, result.refresh_token)
                if request.account_id
                else self._create_from_qr(request, result.cookies, result.refresh_token)
            )
        finally:
            self._qr_challenges.pop(challenge_id, None)
        return BilibiliQrPollResponse(status="completed", message=result.message, account=account)

    def refresh(self, account_id: str, *, force: bool = False) -> AccountResponse:
        account = self.storage.get_account(account_id)
        cookie_file = self.resolve_cookie_file(account_id, "bilibili", require_usable=False)
        token_path = cookie_file.parent / "refresh-token.txt"
        if not account.auto_refresh or not token_path.is_file():
            raise AccountConflictError("This account has no refresh token. Sign in with a QR code to enable automatic renewal.")
        lock = self._refresh_locks.setdefault(account_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise AccountConflictError("This account is already being refreshed.")
        temporary = cookie_file.with_suffix(".refresh.tmp")
        token_temporary = token_path.with_suffix(".tmp")
        try:
            required, timestamp = self.bilibili.cookie_refresh_required(cookie_file)
            if not required and not force:
                identity = self.bilibili.verify(cookie_file)
                return self.response(self.storage.update_account(
                    account_id, external_id=identity.external_id, display_name=identity.display_name,
                    avatar_url=identity.avatar_url, vip_type=identity.vip_type, state="valid",
                    last_verified_at=utc_now(), last_refresh_check_at=utc_now(),
                    last_refresh_error=None, last_error=None,
                ))
            old_token = token_path.read_text(encoding="utf-8").strip()
            refreshed = self.bilibili.refresh_cookies(cookie_file, old_token, timestamp)
            self._write_cookie_jar(temporary, refreshed.cookies)
            identity = self.bilibili.verify(temporary)
            self._write_secret_file(token_temporary, refreshed.refresh_token)
            temporary.replace(cookie_file)
            token_temporary.replace(token_path)
            now = utc_now()
            confirm_error: str | None = None
            try:
                self.bilibili.confirm_cookie_refresh(cookie_file, refreshed.old_refresh_token)
            except Exception as exc:
                confirm_error = f"Credentials renewed, but old-session confirmation failed: {exc}"
            return self.response(self.storage.update_account(
                account_id, external_id=identity.external_id, display_name=identity.display_name,
                avatar_url=identity.avatar_url, vip_type=identity.vip_type, state="valid",
                last_verified_at=now, last_refresh_at=now, last_refresh_check_at=now,
                last_refresh_error=confirm_error, last_error=None,
            ))
        except Exception as exc:
            fields: dict[str, object] = {"last_refresh_check_at": utc_now(), "last_refresh_error": str(exc)}
            if isinstance(exc, BilibiliProviderError) and exc.code == "account_login_invalid":
                fields.update(state="invalid", last_verified_at=utc_now(), last_error=str(exc))
            self.storage.update_account(account_id, **fields)
            raise
        finally:
            temporary.unlink(missing_ok=True)
            token_temporary.unlink(missing_ok=True)
            lock.release()

    def _replace_from_qr(self, account_id: str, cookies: object, refresh_token: str) -> AccountResponse:
        account = self.storage.get_account(account_id)
        target = self.resolve_cookie_file(account_id, "bilibili", require_usable=False)
        cookie_temporary = target.with_suffix(".qr.tmp")
        token_path = target.parent / "refresh-token.txt"
        token_temporary = token_path.with_suffix(".tmp")
        try:
            self._write_cookie_jar(cookie_temporary, cookies)
            identity = self.bilibili.verify(cookie_temporary)
            if account.external_id and identity.external_id != account.external_id:
                raise AccountConflictError("The scanned Bilibili identity does not match this account.")
            duplicate = next((item for item in self.storage.list_accounts("bilibili") if item.id != account.id and item.external_id == identity.external_id), None)
            if duplicate:
                raise AccountConflictError("This Bilibili identity is already configured in another account.")
            self._write_secret_file(token_temporary, refresh_token)
            cookie_temporary.replace(target)
            token_temporary.replace(token_path)
            return self.response(self.storage.update_account(
                account.id, external_id=identity.external_id, display_name=identity.display_name,
                avatar_url=identity.avatar_url, vip_type=identity.vip_type, state="valid",
                login_method="qr", auto_refresh=True, last_refresh_at=None,
                last_refresh_check_at=None, last_refresh_error=None,
                last_verified_at=utc_now(), last_error=None,
            ))
        finally:
            cookie_temporary.unlink(missing_ok=True)
            token_temporary.unlink(missing_ok=True)

    def _create_from_qr(self, request: BilibiliQrStartRequest, cookies: object, refresh_token: str) -> AccountResponse:
        account_id = uuid.uuid4().hex
        directory = self.accounts_dir / account_id
        directory.mkdir(parents=True, exist_ok=False)
        target = directory / "cookies.txt"
        try:
            self._write_cookie_jar(target, cookies)
            self._write_secret_file(directory / "refresh-token.txt", refresh_token)
            identity = self.bilibili.verify(target)
            if any(item.external_id == identity.external_id for item in self.storage.list_accounts("bilibili")):
                raise AccountConflictError("This Bilibili identity is already configured.")
            make_default = request.make_default or not self.storage.list_accounts("bilibili")
            account = self.storage.create_account(account_id, "bilibili", request.label.strip(), f"accounts/{account_id}/cookies.txt", make_default)
            account = self.storage.update_account(
                account.id, external_id=identity.external_id, display_name=identity.display_name,
                avatar_url=identity.avatar_url, vip_type=identity.vip_type, state="valid",
                login_method="qr", auto_refresh=True, last_verified_at=utc_now(), last_error=None,
                last_refresh_error=None,
            )
            return self.response(account)
        except Exception:
            try:
                self.storage.delete_account(account_id)
            except KeyError:
                pass
            shutil.rmtree(directory, ignore_errors=True)
            raise

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
        if require_usable and account.state in {"invalid", "expired"}:
            platform_name = "Bilibili" if account.platform == "bilibili" else "Douyin"
            raise AccountConflictError(f"The selected {platform_name} account login is invalid. Replace its cookies and verify the account again.")
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
        provider = self._provider(account.platform)
        operation = getattr(provider, "list_resources", None)
        if operation is None:
            raise ProviderError("resource_not_found", "This account provider does not support library browsing.", 404)
        lock = self._resource_lock(account_id)
        try:
            with lock:
                return operation(account, self.resolve_cookie_file(account_id, account.platform), kind, offset, limit)
        except ProviderError as exc:
            self._record_provider_error(account_id, exc)
            raise

    def list_entries(
        self,
        account_id: str,
        resource_id: str,
        offset: int,
        limit: int,
        known_total: int | None = None,
    ) -> AccountResourceEntriesResponse:
        account = self.storage.get_account(account_id)
        provider = self._provider(account.platform)
        operation = getattr(provider, "list_entries", None)
        if operation is None:
            raise ProviderError("resource_not_found", "This account provider does not support library browsing.", 404)
        lock = self._resource_lock(account_id)
        try:
            with lock:
                result = operation(account, self.resolve_cookie_file(account_id, account.platform), resource_id, offset, limit)
            if known_total is not None and known_total > result.page.total:
                total = known_total
                result = result.model_copy(update={
                    "resource": result.resource.model_copy(update={"item_count": total}),
                    "page": result.page.model_copy(update={
                        "total": total,
                        "has_more": offset + len(result.entries) < total,
                    }),
                })
            return result
        except ProviderError as exc:
            self._record_provider_error(account_id, exc)
            raise

    def _resource_lock(self, account_id: str) -> threading.Lock:
        with self._resource_locks_guard:
            return self._resource_locks.setdefault(account_id, threading.Lock())

    def _record_provider_error(self, account_id: str, exc: ProviderError) -> None:
        if exc.code == "account_login_invalid":
            self.storage.update_account(account_id, state="invalid", last_verified_at=utc_now(), last_error=str(exc))

    def douyin_video_info(self, account_id: str, canonical_url: str) -> dict[str, object]:
        account = self.storage.get_account(account_id)
        if account.platform != "douyin":
            raise AccountConflictError("The selected account does not match this platform.")
        lock = self._resource_lock(account_id)
        try:
            with lock:
                return self.douyin.video_info(
                    self.resolve_cookie_file(account_id, "douyin"),
                    canonical_url,
                )
        except ProviderError as exc:
            self._record_provider_error(account_id, exc)
            raise

    def resolve_douyin_thumbnail(self, token: str) -> str:
        return self.douyin.resolve_image(token)

    def list_all_entries(self, account_id: str, resource_id: str) -> tuple[AccountResource, list[PlaylistEntry]]:
        account = self.storage.get_account(account_id)
        try:
            return self.bilibili.list_all_entries(
                account,
                self.resolve_cookie_file(account_id, "bilibili"),
                resource_id,
            )
        except BilibiliProviderError as exc:
            if exc.code == "account_login_invalid":
                self.storage.update_account(account_id, state="invalid", last_verified_at=utc_now(), last_error=str(exc))
            raise

    def expand_playlist_entries(self, account_id: str, entries: list[PlaylistEntry]) -> list[PlaylistEntry]:
        account = self.storage.get_account(account_id)
        try:
            return self.bilibili.expand_entries(
                account,
                self.resolve_cookie_file(account_id, "bilibili"),
                entries,
            )
        except BilibiliProviderError as exc:
            if exc.code == "account_login_invalid":
                self.storage.update_account(account_id, state="invalid", last_verified_at=utc_now(), last_error=str(exc))
            raise

    def _provider(self, platform: str) -> AccountProvider:
        provider = self.providers.get(platform)
        if provider is None:
            raise AccountConflictError(f"Unsupported account platform: {platform}")
        return provider

    @staticmethod
    def _cookie_domain(provider: AccountProvider, platform: str) -> str:
        return getattr(provider, "cookie_domain", f".{platform}.com")

    def _verify_import(
        self,
        provider: AccountProvider,
        cookie_file: Path,
    ) -> tuple[PlatformIdentity | None, str, str | None]:
        try:
            if hasattr(provider, "validate_cookie_file"):
                provider.validate_cookie_file(cookie_file)
            return provider.verify(cookie_file), "valid", None
        except ProviderError as exc:
            if not getattr(provider, "allow_unverified_import", False) or exc.code == "account_login_invalid":
                raise
            return None, "unknown", str(exc)

    def _ensure_identity_available(
        self,
        platform: str,
        external_id: str,
        *,
        exclude_account_id: str | None = None,
    ) -> None:
        duplicate = next((
            item for item in self.storage.list_accounts(platform)
            if item.id != exclude_account_id and item.external_id == external_id
        ), None)
        if duplicate:
            platform_name = "Bilibili" if platform == "bilibili" else "Douyin"
            raise AccountConflictError(f"This {platform_name} identity is already configured.")

    @staticmethod
    def _identity_fields(identity: PlatformIdentity) -> dict[str, object]:
        return {
            "external_id": identity.external_id,
            "display_name": identity.display_name,
            "avatar_url": identity.avatar_url,
            "vip_type": identity.vip_type,
        }

    def response(self, account: PlatformAccount) -> AccountResponse:
        status = cookie_profile_status(self.resolve_cookie_file(account.id, account.platform, require_usable=False))
        return AccountResponse(
            id=account.id, platform=account.platform, label=account.label, external_id=account.external_id,
            display_name=account.display_name, avatar_url=account.avatar_url, vip_type=account.vip_type,
            state=account.state, cookie_status=status, login_method=account.login_method,
            auto_refresh=account.auto_refresh, last_refresh_at=account.last_refresh_at,
            last_refresh_check_at=account.last_refresh_check_at,
            last_refresh_error=account.last_refresh_error, is_default=account.is_default,
            last_verified_at=account.last_verified_at, last_error=account.last_error,
            created_at=account.created_at, updated_at=account.updated_at,
        )

    async def _warm_douyin_accounts(self) -> None:
        try:
            accounts = [
                account for account in self.storage.list_accounts("douyin")
                if account.state not in {"invalid", "expired"}
            ]
        except Exception:
            return
        await asyncio.gather(
            *(asyncio.to_thread(self._warm_douyin_account, account) for account in accounts),
            return_exceptions=True,
        )

    def _warm_douyin_account(self, account: PlatformAccount) -> None:
        warm = getattr(self.douyin, "warm", None)
        if warm is None or account.platform != "douyin" or account.state in {"invalid", "expired"}:
            return
        try:
            cookie_file = self.resolve_cookie_file(account.id, "douyin")
            warm(account, cookie_file)
        except Exception:
            pass

    async def _maintenance_loop(self) -> None:
        while True:
            try:
                accounts = self.storage.list_accounts("bilibili")
            except Exception:
                accounts = []
            for account in accounts:
                if not account.auto_refresh:
                    continue
                if account.last_refresh_check_at:
                    try:
                        checked = datetime.fromisoformat(account.last_refresh_check_at)
                        if (datetime.now(timezone.utc) - checked).total_seconds() < 24 * 60 * 60:
                            continue
                    except ValueError:
                        pass
                try:
                    await asyncio.to_thread(self.refresh, account.id)
                except Exception:
                    pass
            await asyncio.sleep(60 * 60)

    @staticmethod
    def _write_secret_file(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _write_cookie_jar(path: Path, cookies: object) -> None:
        jar = MozillaCookieJar(str(path))
        for cookie in cookies:  # type: ignore[union-attr]
            jar.set_cookie(cookie)
        jar.save(ignore_discard=True, ignore_expires=True)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    @staticmethod
    def _write_cookie_file(path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
