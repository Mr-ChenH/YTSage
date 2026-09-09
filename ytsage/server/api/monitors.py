from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..models import PlaylistMonitorCreate, PlaylistMonitorCreateResponse, PlaylistMonitorLogListResponse, PlaylistMonitorResponse, PlaylistMonitorUpdate
from ..services.playlist_monitor import PlaylistMonitorService

AuthDependency = Callable[..., None]


def create_monitors_router(service: PlaylistMonitorService, auth_dependency: AuthDependency) -> APIRouter:
    router = APIRouter(prefix="/api/monitors", dependencies=[Depends(auth_dependency)])

    @router.get("", response_model=list[PlaylistMonitorResponse])
    def list_monitors() -> list[PlaylistMonitorResponse]:
        return service.list()

    @router.post("", response_model=PlaylistMonitorCreateResponse)
    async def create_monitor(request: PlaylistMonitorCreate) -> PlaylistMonitorCreateResponse:
        try:
            return await service.create(request)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/{monitor_id}/logs", response_model=PlaylistMonitorLogListResponse)
    def list_monitor_logs(
        monitor_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> PlaylistMonitorLogListResponse:
        try:
            return service.list_logs(monitor_id, offset=offset, limit=limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Monitor not found") from exc

    @router.patch("/{monitor_id}", response_model=PlaylistMonitorResponse)
    def update_monitor(monitor_id: str, request: PlaylistMonitorUpdate) -> PlaylistMonitorResponse:
        try:
            return service.update(monitor_id, request.enabled, request.interval_minutes)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Monitor not found") from exc

    @router.post("/{monitor_id}/check", response_model=PlaylistMonitorResponse)
    async def check_monitor(monitor_id: str) -> PlaylistMonitorResponse:
        try:
            return await service.check_now(monitor_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Monitor not found") from exc

    @router.delete("/{monitor_id}", status_code=204)
    def delete_monitor(monitor_id: str) -> Response:
        try:
            service.delete(monitor_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Monitor not found") from exc
        return Response(status_code=204)

    return router
