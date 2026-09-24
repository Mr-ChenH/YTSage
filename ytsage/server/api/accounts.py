from __future__ import annotations

from typing import Callable
from urllib.parse import urljoin, urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..models import AccountCreateRequest, AccountResponse, AccountResourceEntriesResponse, AccountResourceListResponse, AccountUpdateRequest, BilibiliQrPollResponse, BilibiliQrStartRequest, BilibiliQrStartResponse
from ..providers.base import ProviderError
from ..providers.bilibili import BilibiliProviderError, _AVATAR_HOST_SUFFIXES, _HEADERS, normalize_image_url
from ..providers.douyin import _AVATAR_HOST_SUFFIXES as _DOUYIN_AVATAR_HOST_SUFFIXES
from ..providers.douyin import _HEADERS as _DOUYIN_HEADERS
from ..services.accounts import AccountConflictError, AccountService

AuthDependency = Callable[..., None]
_MAX_IMAGE_BYTES = 5 * 1024 * 1024
_MAX_IMAGE_REDIRECTS = 3
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _provider_http_error(exc: ProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


def _validated_image_url(platform: str, image_url: str, suffixes: tuple[str, ...]) -> str:
    parsed = urlparse(image_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Unsupported {platform} image URL") from exc
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
        or not any(host.endswith(suffix) for suffix in suffixes)
    ):
        raise HTTPException(status_code=422, detail=f"Unsupported {platform} image URL")
    return image_url


def _read_bounded_image(upstream: object) -> bytes:
    content_length = getattr(upstream, "headers", {}).get("Content-Length")
    try:
        if content_length is not None and int(content_length) > _MAX_IMAGE_BYTES:
            raise HTTPException(status_code=502, detail="Platform image response is too large")
    except ValueError:
        pass
    iterator = getattr(upstream, "iter_content", None)
    chunks = iterator(chunk_size=64 * 1024) if callable(iterator) else (getattr(upstream, "content", b""),)
    try:
        chunks = iter(chunks)
    except TypeError:
        chunks = iter((getattr(upstream, "content", b""),))
    body = bytearray()
    for chunk in chunks:
        if not chunk:
            continue
        body.extend(chunk)
        if len(body) > _MAX_IMAGE_BYTES:
            raise HTTPException(status_code=502, detail="Platform image response is too large")
    return bytes(body)


def _fetch_platform_image(platform: str, image_url: str) -> Response:
    if platform == "bilibili":
        image_url = normalize_image_url(image_url) or image_url
        suffixes = _AVATAR_HOST_SUFFIXES
        request_headers = _HEADERS
    elif platform == "douyin":
        parsed_input = urlparse(image_url)
        if parsed_input.scheme == "http":
            image_url = f"https://{parsed_input.netloc}{parsed_input.path}" + (f"?{parsed_input.query}" if parsed_input.query else "")
        suffixes = _DOUYIN_AVATAR_HOST_SUFFIXES
        request_headers = _DOUYIN_HEADERS
    else:
        raise HTTPException(status_code=422, detail="Unsupported account image platform")
    current_url = _validated_image_url(platform, image_url, suffixes)
    upstream = None
    try:
        for redirect_count in range(_MAX_IMAGE_REDIRECTS + 1):
            upstream = requests.get(
                current_url,
                headers=request_headers,
                timeout=15,
                allow_redirects=False,
                stream=True,
            )
            if upstream.status_code not in _REDIRECT_STATUSES:
                upstream.raise_for_status()
                break
            location = upstream.headers.get("Location")
            close = getattr(upstream, "close", None)
            if close:
                close()
            if not location or redirect_count == _MAX_IMAGE_REDIRECTS:
                raise HTTPException(status_code=502, detail=f"Unable to fetch {platform} image")
            current_url = _validated_image_url(platform, urljoin(current_url, location), suffixes)
        content_type = upstream.headers.get("Content-Type", "")
        if not content_type.lower().startswith("image/"):
            raise HTTPException(status_code=502, detail="Platform image response is not an image")
        content = _read_bounded_image(upstream)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Unable to fetch {platform} image") from exc
    finally:
        close = getattr(upstream, "close", None)
        if close:
            close()
    return Response(
        content=content,
        media_type=content_type.split(";", 1)[0],
        headers={"Cache-Control": "private, max-age=3600"},
    )


def _fetch_bilibili_image(image_url: str) -> Response:
    return _fetch_platform_image("bilibili", image_url)


def _fetch_avatar(avatar_url: str) -> Response:
    return _fetch_bilibili_image(avatar_url)


def create_accounts_router(service: AccountService, auth_dependency: AuthDependency) -> APIRouter:
    router = APIRouter(prefix="/api/accounts", dependencies=[Depends(auth_dependency)])

    @router.get("", response_model=list[AccountResponse])
    def list_accounts(platform: str | None = Query(default=None)) -> list[AccountResponse]:
        return service.list(platform)

    @router.post("", response_model=AccountResponse, status_code=201)
    def create_account(request: AccountCreateRequest) -> AccountResponse:
        try:
            return service.create(request)
        except ProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/bilibili/qr", response_model=BilibiliQrStartResponse, status_code=201)
    def start_bilibili_qr(request: BilibiliQrStartRequest) -> BilibiliQrStartResponse:
        try:
            return service.start_qr_login(request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        except BilibiliProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/bilibili/qr/{challenge_id}", response_model=BilibiliQrPollResponse)
    def poll_bilibili_qr(challenge_id: str) -> BilibiliQrPollResponse:
        try:
            return service.poll_qr_login(challenge_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="QR login challenge not found or expired") from exc
        except BilibiliProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{account_id}/refresh", response_model=AccountResponse)
    def refresh_account(account_id: str, force: bool = Query(default=False)) -> AccountResponse:
        try:
            return service.refresh(account_id, force=force)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        except BilibiliProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/{account_id}", response_model=AccountResponse)
    def get_account(account_id: str) -> AccountResponse:
        try:
            return service.get(account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc

    @router.get("/{account_id}/avatar", response_model=None)
    def account_avatar(account_id: str) -> Response:
        try:
            account = service.get(account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        if not account.avatar_url:
            raise HTTPException(status_code=404, detail="Account avatar not found")
        return _fetch_platform_image(account.platform, account.avatar_url)

    @router.get("/{account_id}/image", response_model=None)
    def account_image(account_id: str, url: str = Query(max_length=2048)) -> Response:
        try:
            account = service.get(account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        if account.platform not in {"bilibili", "douyin"}:
            raise HTTPException(status_code=422, detail="Library images are unavailable for this account platform")
        return _fetch_platform_image(account.platform, url)

    @router.patch("/{account_id}", response_model=AccountResponse)
    def update_account(account_id: str, request: AccountUpdateRequest) -> AccountResponse:
        try:
            return service.update(account_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        except ProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/{account_id}/verify", response_model=AccountResponse)
    def verify_account(account_id: str) -> AccountResponse:
        try:
            return service.verify(account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        except ProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.post("/{account_id}/default", response_model=AccountResponse)
    def default_account(account_id: str) -> AccountResponse:
        try:
            return service.update(account_id, AccountUpdateRequest(make_default=True))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc

    @router.delete("/{account_id}", status_code=204)
    def delete_account(account_id: str) -> Response:
        try:
            service.delete(account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(status_code=204)

    @router.get("/{account_id}/resources", response_model=AccountResourceListResponse)
    def list_resources(
        account_id: str,
        kind: str = Query(default="created_favorite"),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> AccountResourceListResponse:
        try:
            return service.list_resources(account_id, kind, offset, limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        except ProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=424, detail=str(exc)) from exc

    @router.get("/{account_id}/resources/{resource_id}/entries", response_model=AccountResourceEntriesResponse)
    def list_entries(
        account_id: str,
        resource_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
        known_total: int | None = Query(default=None, ge=0),
    ) -> AccountResourceEntriesResponse:
        try:
            return service.list_entries(account_id, resource_id, offset, limit, known_total)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        except ProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=424, detail=str(exc)) from exc

    return router
