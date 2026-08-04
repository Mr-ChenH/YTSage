"""FastAPI application for YTSage Server."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import ServerConfig, load_config
from .models import AnalyzeRequest, AnalyzeResponse, CookieSaveRequest, CookieSaveResponse, CreateTaskRequest, DependencyUpdateResponse, FilenameTemplateSaveRequest, HealthResponse, SettingsResponse, TaskResponse
from .services import analyzer
from .services.auth import require_auth, require_websocket_auth
from .services.cookies import configured_cookie_profiles, cookie_file_path, normalize_cookie_profile, normalize_cookies
from .services.dependencies import ensure_runtime_dependencies, ffmpeg_version, update_runtime_dependencies, ytdlp_version
from .services.files import folder_download_response, folder_manifest_response, list_files, ranged_download_response, resolve_download_file, resolve_download_folder, stream_response
from .services.settings import default_video_resolution, filename_template, save_default_video_resolution, save_filename_template
from .services.storage import Storage
from .services.task_manager import TaskManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager: TaskManager = app.state.task_manager
    ensure_runtime_dependencies()
    await manager.start()
    try:
        yield
    finally:
        await manager.stop()


def create_app() -> FastAPI:
    config = load_config()
    storage = Storage(config.database_path)
    manager = TaskManager(config, storage)

    app = FastAPI(title="YTSage Server", version="5.2.0-server", lifespan=lifespan)
    app.state.config = config
    app.state.storage = storage
    app.state.task_manager = manager

    def auth_dependency(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
        require_auth(config, request, authorization)

    @app.get("/api/health", response_model=HealthResponse)
    def health(_: None = Depends(auth_dependency)) -> HealthResponse:
        download_writable = _is_writable(config.download_dir)
        config_writable = _is_writable(config.config_dir)
        yt_dlp = ytdlp_version()
        ffmpeg = ffmpeg_version()
        return HealthResponse(
            healthy=download_writable and config_writable and yt_dlp != "not found" and ffmpeg != "not found",
            download_dir_writable=download_writable,
            config_dir_writable=config_writable,
            yt_dlp=yt_dlp,
            ffmpeg=ffmpeg,
            queue_concurrency=config.queue_concurrency,
            auth_configured=bool(config.auth_token),
        )

    @app.post("/api/dependencies/update", response_model=DependencyUpdateResponse)
    def update_dependencies(_: None = Depends(auth_dependency)) -> DependencyUpdateResponse:
        return DependencyUpdateResponse(**update_runtime_dependencies())

    @app.get("/api/settings", response_model=SettingsResponse)
    def settings(_: None = Depends(auth_dependency)) -> SettingsResponse:
        profiles = configured_cookie_profiles(config.config_dir)
        return SettingsResponse(
            download_dir=str(config.download_dir),
            config_dir=str(config.config_dir),
            queue_concurrency=config.queue_concurrency,
            auth_configured=bool(config.auth_token),
            cookies_configured=any(profiles.values()),
            cookie_profiles=profiles,
            filename_template=filename_template(config.config_dir),
            default_video_resolution=default_video_resolution(config.config_dir),
        )

    @app.post("/api/settings/cookies", response_model=CookieSaveResponse)
    def save_cookies(request: CookieSaveRequest, _: None = Depends(auth_dependency)) -> CookieSaveResponse:
        profile = normalize_cookie_profile(request.profile)
        normalized = normalize_cookies(request.content)
        target = cookie_file_path(config.config_dir, profile)
        if normalized is None:
            target.unlink(missing_ok=True)
            return CookieSaveResponse(cookies_configured=False, profile=profile)
        target.write_text(normalized, encoding="utf-8")
        return CookieSaveResponse(cookies_configured=True, profile=profile)

    @app.post("/api/settings/filename-template", response_model=SettingsResponse)
    def save_template(request: FilenameTemplateSaveRequest, _: None = Depends(auth_dependency)) -> SettingsResponse:
        save_filename_template(config.config_dir, request.filename_template)
        if request.default_video_resolution is not None:
            save_default_video_resolution(config.config_dir, request.default_video_resolution)
        return settings()

    @app.post("/api/analyze", response_model=AnalyzeResponse)
    def analyze_url(request: AnalyzeRequest, _: None = Depends(auth_dependency)) -> AnalyzeResponse:
        return analyzer.analyze(request, config_dir=config.config_dir)

    @app.post("/api/tasks", response_model=TaskResponse)
    async def create_task(request: CreateTaskRequest, _: None = Depends(auth_dependency)) -> TaskResponse:
        if not request.filename_template.strip():
            request.filename_template = filename_template(config.config_dir)
        return await manager.create_task(request)

    @app.get("/api/tasks", response_model=list[TaskResponse])
    def list_tasks(_: None = Depends(auth_dependency)) -> list[TaskResponse]:
        return manager.list_tasks()

    @app.get("/api/tasks/{task_id}", response_model=TaskResponse)
    def get_task(task_id: str, _: None = Depends(auth_dependency)) -> TaskResponse:
        try:
            return manager.get_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc

    @app.post("/api/tasks/{task_id}/cancel", response_model=TaskResponse)
    async def cancel_task(task_id: str, _: None = Depends(auth_dependency)) -> TaskResponse:
        try:
            return await manager.cancel_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc

    @app.post("/api/tasks/{task_id}/retry-playlist-item/{playlist_index}", response_model=TaskResponse)
    async def retry_playlist_item(task_id: str, playlist_index: int, _: None = Depends(auth_dependency)) -> TaskResponse:
        try:
            return await manager.retry_playlist_item(task_id, playlist_index)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Playlist item not found") from exc

    @app.delete("/api/tasks/{task_id}", status_code=204)
    async def delete_task(task_id: str, _: None = Depends(auth_dependency)) -> Response:
        try:
            await manager.delete_task(task_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Task not found") from exc
        return Response(status_code=204)

    @app.delete("/api/tasks", status_code=204)
    def clear_tasks(_: None = Depends(auth_dependency)) -> Response:
        manager.clear_finished_tasks()
        return Response(status_code=204)

    @app.websocket("/api/events")
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

    @app.get("/api/history")
    def history(limit: int = Query(100, ge=1, le=500), _: None = Depends(auth_dependency)):
        return storage.list_history(limit=limit)

    @app.delete("/api/history/{history_id}", status_code=204)
    def delete_history(history_id: str, _: None = Depends(auth_dependency)) -> Response:
        try:
            storage.delete_history(history_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="History entry not found") from exc
        return Response(status_code=204)

    @app.delete("/api/history", status_code=204)
    def clear_history(_: None = Depends(auth_dependency)) -> Response:
        storage.clear_history()
        return Response(status_code=204)

    @app.get("/api/files")
    def files(
        request: Request,
        q: str | None = None,
        folder: str | None = None,
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=200),
        _: None = Depends(auth_dependency),
    ):
        return list_files(config.download_dir, request, query=q, folder=folder, offset=offset, limit=limit)

    @app.get("/api/folders/download", name="download_folder")
    def download_folder(folder: str | None = None, _: None = Depends(auth_dependency)):
        folder_path, archive_name = resolve_download_folder(config.download_dir, folder)
        return folder_download_response(folder_path, archive_name)

    @app.get("/api/folders/manifest", name="folder_manifest")
    def folder_manifest(request: Request, folder: str | None = None, format: str = "aria2", _: None = Depends(auth_dependency)):
        folder_path, archive_name = resolve_download_folder(config.download_dir, folder)
        return folder_manifest_response(config.download_dir, folder_path, archive_name, request, format)

    @app.get("/api/files/{file_id}/download", name="download_file")
    def download_file(file_id: str, range_header: Annotated[str | None, Header(alias="Range")] = None, _: None = Depends(auth_dependency)):
        return ranged_download_response(resolve_download_file(config.download_dir, file_id), range_header)

    @app.get("/api/files/{file_id}/stream", name="stream_file")
    def stream_file(file_id: str, range_header: Annotated[str | None, Header(alias="Range")] = None, _: None = Depends(auth_dependency)):
        return stream_response(resolve_download_file(config.download_dir, file_id), range_header)

    if config.static_dir.exists():
        app.mount("/static", StaticFiles(directory=config.static_dir), name="static")

    @app.get("/", response_class=HTMLResponse, response_model=None)
    def index():
        index_path = config.static_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return HTMLResponse("<h1>YTSage Server</h1><p>Static UI is not built.</p>")

    return app


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".ytsage-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


app = create_app()


def main() -> None:
    config = load_config()
    uvicorn.run("ytsage.server.app:app", host=config.host, port=config.port)


if __name__ == "__main__":
    main()
