from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import APIRouter, Depends, Query

from ..config import ServerConfig
from ..models import CookieSaveRequest, CookieSaveResponse, DependencyUpdateResponse, FilenameTemplateSaveRequest, HealthResponse, SettingsResponse
from ..services.cookies import clear_cookie_login_status, configured_cookie_profiles, cookie_domain_for_profile, cookie_file_path, cookie_profile_status, cookie_profile_statuses, normalize_cookie_profile, normalize_cookies
from ..services.dependencies import ffmpeg_version, ytdlp_version
from ..services.dependency_updates import DependencyUpdateManager
from ..services.settings import default_video_resolution, filename_template, save_default_video_resolution, save_filename_template
from ..providers.douyin_browser import chromium_capability

AuthDependency = Callable[..., None]


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".ytsage-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def create_system_router(config: ServerConfig, auth_dependency: AuthDependency) -> APIRouter:
    router = APIRouter(prefix="/api", dependencies=[Depends(auth_dependency)])
    dependency_updates = DependencyUpdateManager()

    def settings_response() -> SettingsResponse:
        profiles = configured_cookie_profiles(config.config_dir)
        profile_status = cookie_profile_statuses(config.config_dir)
        return SettingsResponse(download_dir=str(config.download_dir), config_dir=str(config.config_dir), queue_concurrency=config.queue_concurrency, auth_configured=bool(config.auth_token), cookies_configured=any(profiles.values()), cookie_profiles=profiles, cookie_profile_status=profile_status, filename_template=filename_template(config.config_dir), default_video_resolution=default_video_resolution(config.config_dir))

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        download_writable, config_writable = _is_writable(config.download_dir), _is_writable(config.config_dir)
        yt_dlp, ffmpeg = ytdlp_version(), ffmpeg_version()
        browser_available = bool(chromium_capability()["available"])
        return HealthResponse(healthy=download_writable and config_writable and yt_dlp != "not found" and ffmpeg != "not found", download_dir_writable=download_writable, config_dir_writable=config_writable, yt_dlp=yt_dlp, ffmpeg=ffmpeg, queue_concurrency=config.queue_concurrency, auth_configured=bool(config.auth_token), douyin_browser_available=browser_available)

    @router.get("/dependencies", response_model=DependencyUpdateResponse)
    def dependency_status(refresh: bool = Query(default=False)) -> DependencyUpdateResponse:
        current = dependency_updates.status()
        if refresh or current["phase"] == "idle":
            return DependencyUpdateResponse(**dependency_updates.start_check())
        return DependencyUpdateResponse(**current)

    @router.post("/dependencies/update", response_model=DependencyUpdateResponse)
    def update_dependencies() -> DependencyUpdateResponse:
        return DependencyUpdateResponse(**dependency_updates.start_update())

    @router.get("/settings", response_model=SettingsResponse)
    def settings() -> SettingsResponse:
        return settings_response()

    @router.post("/settings/cookies", response_model=CookieSaveResponse)
    def save_cookies(request: CookieSaveRequest) -> CookieSaveResponse:
        profile = normalize_cookie_profile(request.profile)
        normalized = normalize_cookies(request.content, cookie_domain_for_profile(profile))
        target = cookie_file_path(config.config_dir, profile)
        clear_cookie_login_status(config.config_dir, profile)
        if normalized is None:
            target.unlink(missing_ok=True)
            return CookieSaveResponse(cookies_configured=False, profile=profile, status=cookie_profile_status(target))
        target.write_text(normalized, encoding="utf-8")
        saved_status = cookie_profile_status(target)
        return CookieSaveResponse(cookies_configured=saved_status.usable, profile=profile, status=saved_status)

    @router.post("/settings/filename-template", response_model=SettingsResponse)
    def save_template(request: FilenameTemplateSaveRequest) -> SettingsResponse:
        save_filename_template(config.config_dir, request.filename_template)
        if request.default_video_resolution is not None:
            save_default_video_resolution(config.config_dir, request.default_video_resolution)
        return settings_response()

    return router
