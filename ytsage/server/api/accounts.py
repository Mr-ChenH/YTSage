from __future__ import annotations

from typing import Callable
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..models import AccountCreateRequest, AccountResponse, AccountResourceEntriesResponse, AccountResourceListResponse, AccountUpdateRequest
from ..providers.bilibili import BilibiliProviderError, _AVATAR_HOST_SUFFIXES, _HEADERS, normalize_image_url
from ..services.accounts import AccountConflictError, AccountService

AuthDependency = Callable[..., None]


def _provider_http_error(exc: BilibiliProviderError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": str(exc)})


def _fetch_bilibili_image(image_url: str) -> Response:
    image_url = normalize_image_url(image_url) or image_url
    parsed = urlparse(image_url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not any(host.endswith(suffix) for suffix in _AVATAR_HOST_SUFFIXES):
        raise HTTPException(status_code=422, detail="Unsupported Bilibili image URL")
    try:
        upstream = requests.get(image_url, headers=_HEADERS, timeout=15)
        upstream.raise_for_status()
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Unable to fetch Bilibili image") from exc
    content_type = upstream.headers.get("Content-Type", "")
    if not content_type.lower().startswith("image/"):
        raise HTTPException(status_code=502, detail="Bilibili image response is not an image")
    return Response(
        content=upstream.content,
        media_type=content_type.split(";", 1)[0],
        headers={"Cache-Control": "private, max-age=3600"},
    )


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
        except BilibiliProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
        return _fetch_bilibili_image(account.avatar_url)

    @router.get("/{account_id}/image", response_model=None)
    def account_image(account_id: str, url: str = Query(max_length=2048)) -> Response:
        try:
            service.get(account_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        return _fetch_bilibili_image(url)

    @router.patch("/{account_id}", response_model=AccountResponse)
    def update_account(account_id: str, request: AccountUpdateRequest) -> AccountResponse:
        try:
            return service.update(account_id, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        except BilibiliProviderError as exc:
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
        except BilibiliProviderError as exc:
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
        except BilibiliProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=424, detail=str(exc)) from exc

    @router.get("/{account_id}/resources/{resource_id}/entries", response_model=AccountResourceEntriesResponse)
    def list_entries(
        account_id: str,
        resource_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> AccountResourceEntriesResponse:
        try:
            return service.list_entries(account_id, resource_id, offset, limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Account not found") from exc
        except BilibiliProviderError as exc:
            raise _provider_http_error(exc) from exc
        except AccountConflictError as exc:
            raise HTTPException(status_code=424, detail=str(exc)) from exc

    return router
