from __future__ import annotations

import asyncio
import json
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket, WebSocketDisconnect

from ..config import ServerConfig
from ..models import CreateTaskRequest, TaskResponse
from ..services.auth import require_websocket_auth
from ..services.settings import filename_template
from ..services.storage import Storage
from ..services.task_manager import TaskManager

AuthDependency = Callable[..., None]


def create_tasks_router(config: ServerConfig, storage: Storage, manager: TaskManager, auth_dependency: AuthDependency) -> APIRouter:
    router = APIRouter(prefix="/api")
    auth = [Depends(auth_dependency)]

    @router.post("/tasks", response_model=TaskResponse, dependencies=auth)
    async def create_task(request: CreateTaskRequest) -> TaskResponse:
        if not request.filename_template.strip():
            request.filename_template = filename_template(config.config_dir)
        return await manager.create_task(request)

    @router.get("/tasks", response_model=list[TaskResponse], dependencies=auth)
    def list_tasks(offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200), active_only: bool = Query(False)) -> list[TaskResponse]:
        return manager.list_tasks(limit=limit, offset=offset, active_only=active_only)

    @router.get("/tasks/{task_id}", response_model=TaskResponse, dependencies=auth)
    def get_task(task_id: str) -> TaskResponse:
        try:
            return manager.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc

    @router.post("/tasks/{task_id}/cancel", response_model=TaskResponse, dependencies=auth)
    async def cancel_task(task_id: str) -> TaskResponse:
        try:
            return await manager.cancel_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc

    @router.post("/tasks/{task_id}/retry-playlist-item/{playlist_index}", response_model=TaskResponse, dependencies=auth)
    async def retry_playlist_item(task_id: str, playlist_index: int) -> TaskResponse:
        try:
            return await manager.retry_playlist_item(task_id, playlist_index)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Playlist item not found") from exc

    @router.delete("/tasks/{task_id}", status_code=204, dependencies=auth)
    async def delete_task(task_id: str) -> Response:
        try:
            await manager.delete_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        return Response(status_code=204)

    @router.delete("/tasks", status_code=204, dependencies=auth)
    def clear_tasks() -> Response:
        manager.clear_finished_tasks()
        return Response(status_code=204)

    @router.websocket("/events")
    async def task_events(websocket: WebSocket) -> None:
        if not await require_websocket_auth(config, websocket):
            await websocket.close(code=1008)
            return
        await websocket.accept()
        queue = await manager.subscribe()
        try:
            while True:
                event = await queue.get()
                payload = event.model_dump() if hasattr(event, "model_dump") else event.dict()
                await websocket.send_text(json.dumps(payload))
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            manager.unsubscribe(queue)

    @router.get("/history", dependencies=auth)
    def history(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        return storage.list_history(limit=limit, offset=offset)

    @router.delete("/history/{history_id}", status_code=204, dependencies=auth)
    def delete_history(history_id: str) -> Response:
        try:
            storage.delete_history(history_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="History entry not found") from exc
        return Response(status_code=204)

    @router.delete("/history", status_code=204, dependencies=auth)
    def clear_history() -> Response:
        storage.clear_history()
        return Response(status_code=204)

    return router
