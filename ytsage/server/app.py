"""FastAPI application composition and CLI entrypoint."""

from __future__ import annotations

import signal
import threading
from contextlib import asynccontextmanager, contextmanager
from typing import Annotated

import uvicorn
from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.server import HANDLED_SIGNALS

from .api.accounts import create_accounts_router
from .api.analysis import create_analysis_router
from .api.files import create_files_router
from .api.monitors import create_monitors_router
from .api.system import create_system_router
from .api.tasks import create_tasks_router
from .config import load_config
from .services import analyzer
from .services.accounts import AccountService
from .services.auth import require_auth
from .services.dependencies import ensure_runtime_dependencies
from .services.playlist_monitor import PlaylistMonitorService
from .services.storage import Storage
from .services.task_manager import TaskManager


@asynccontextmanager
async def lifespan(app: FastAPI):
    manager: TaskManager = app.state.task_manager
    monitor_service: PlaylistMonitorService = app.state.monitor_service
    ensure_runtime_dependencies()
    await manager.start()
    await monitor_service.start()
    try:
        yield
    finally:
        await monitor_service.stop()
        await manager.stop()


def create_app() -> FastAPI:
    config = load_config()
    storage = Storage(config.database_path)
    account_service = AccountService(config.config_dir, storage)
    manager = TaskManager(config, storage, account_service)
    monitor_service = PlaylistMonitorService(
        storage,
        manager,
        lambda request: analyzer.analyze(request, config_dir=config.config_dir, account_service=account_service),
    )
    app = FastAPI(title="YTSage Server", version="5.2.0-server", lifespan=lifespan)
    app.state.config = config
    app.state.storage = storage
    app.state.account_service = account_service
    app.state.task_manager = manager
    app.state.monitor_service = monitor_service

    def auth_dependency(request: Request, authorization: Annotated[str | None, Header()] = None) -> None:
        require_auth(config, request, authorization)

    app.include_router(create_system_router(config, auth_dependency))
    app.include_router(create_accounts_router(account_service, auth_dependency))
    app.include_router(create_analysis_router(config, account_service, auth_dependency))
    app.include_router(create_tasks_router(config, storage, manager, auth_dependency))
    app.include_router(create_monitors_router(monitor_service, auth_dependency))
    app.include_router(create_files_router(config, auth_dependency))

    if config.static_dir.exists():
        app.mount("/static", StaticFiles(directory=config.static_dir), name="static")

    @app.get("/", response_class=HTMLResponse, response_model=None)
    def index():
        index_path = config.static_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return HTMLResponse("<h1>YTSage Server</h1><p>Static UI is not built.</p>")

    return app


class QuietSignalServer(uvicorn.Server):
    """Uvicorn variant that keeps graceful Windows shutdown quiet."""

    @contextmanager
    def capture_signals(self):
        if threading.current_thread() is not threading.main_thread():
            yield
            return
        original_handlers = {sig: signal.signal(sig, self.handle_exit) for sig in HANDLED_SIGNALS}
        try:
            yield
        finally:
            for sig, handler in original_handlers.items():
                signal.signal(sig, handler)
            self._captured_signals.clear()


app = create_app()


def main() -> None:
    config = load_config()
    server_config = uvicorn.Config("ytsage.server.app:app", host=config.host, port=config.port)
    QuietSignalServer(server_config).run()


if __name__ == "__main__":
    main()
