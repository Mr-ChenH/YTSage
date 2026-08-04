"""Pydantic models for the YTSage server API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
MediaType = Literal["video", "audio", "subtitle", "other"]
DownloadMode = Literal["video", "audio", "subtitles"]


class FormatInfo(BaseModel):
    format_id: str
    ext: str | None = None
    resolution: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    fps: float | None = None
    filesize: int | None = None
    type: str = "unknown"


class SubtitleInfo(BaseModel):
    language: str
    name: str | None = None
    automatic: bool = False
    formats: list[str] = Field(default_factory=list)


class AnalyzeRequest(BaseModel):
    url: str
    generic_mode: bool = True


class PlaylistEntry(BaseModel):
    index: int
    id: str | None = None
    title: str | None = None
    url: str | None = None
    webpage_url: str | None = None
    duration: float | None = None
    channel: str | None = None
    thumbnail_url: str | None = None


class AnalyzeResponse(BaseModel):
    url: str
    title: str | None = None
    channel: str | None = None
    duration: float | None = None
    thumbnail_url: str | None = None
    is_playlist: bool = False
    playlist_count: int | None = None
    playlist_entries: list[PlaylistEntry] = Field(default_factory=list)
    formats: list[FormatInfo] = Field(default_factory=list)
    subtitles: list[SubtitleInfo] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class CreateTaskRequest(BaseModel):
    url: str
    mode: DownloadMode = "video"
    format_id: str | None = None
    output_format: str = "mp4"
    audio_format: str = "mp3"
    subtitle_langs: list[str] = Field(default_factory=list)
    merge_subtitles: bool = False
    save_thumbnail: bool = False
    save_description: bool = False
    embed_chapters: bool = False
    audio_normalization: bool = False
    rate_limit: str | None = None
    proxy_url: str | None = None
    concurrent_fragments: int | None = Field(default=None, ge=1, le=16)
    cookie_file: str | None = None
    playlist_items: str | None = None
    playlist_title: str | None = None
    playlist_entries: list[PlaylistEntry] = Field(default_factory=list)
    filename_template: str = "%(title)s_%(resolution)s_[%(id)s].%(ext)s"


class TaskProgress(BaseModel):
    percent: float | None = None
    status_text: str | None = None
    speed: str | None = None
    eta: str | None = None
    current_filename: str | None = None
    downloaded_bytes: int | None = None
    playlist_current_index: int | None = None
    playlist_last_index: int | None = None
    playlist_total: int | None = None
    playlist_failed_indexes: list[int] = Field(default_factory=list)
    playlist_failures: dict[str, str] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    id: str
    url: str
    mode: DownloadMode
    status: TaskStatus
    options: dict[str, Any] = Field(default_factory=dict)
    progress: TaskProgress = Field(default_factory=TaskProgress)
    error: str | None = None
    output_path: str | None = None
    created_at: str
    updated_at: str
    started_at: str | None = None
    finished_at: str | None = None


class TaskEvent(BaseModel):
    type: str
    task: TaskResponse


class HistoryEntry(BaseModel):
    id: str
    task_id: str | None = None
    url: str | None = None
    title: str | None = None
    output_path: str | None = None
    file_size: int | None = None
    media_type: MediaType = "other"
    status: str = "completed"
    downloaded_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class FileEntry(BaseModel):
    id: str
    name: str
    relative_path: str
    size: int
    modified_at: str
    media_type: MediaType
    playable: bool
    download_url: str
    stream_url: str | None = None


class FileListResponse(BaseModel):
    root: str
    files: list[FileEntry]
    folders: list[str] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50
    query: str | None = None
    folder: str | None = None


class CookieSaveRequest(BaseModel):
    content: str = Field(max_length=2_000_000)
    profile: str = "default"


class CookieSaveResponse(BaseModel):
    cookies_configured: bool
    profile: str = "default"


class FilenameTemplateSaveRequest(BaseModel):
    filename_template: str = Field(min_length=1, max_length=300)
    default_video_resolution: str | None = Field(default=None, max_length=20)


class SettingsResponse(BaseModel):
    download_dir: str
    config_dir: str
    queue_concurrency: int
    auth_configured: bool
    cookies_configured: bool = False
    cookie_profiles: dict[str, bool] = Field(default_factory=dict)
    filename_template: str
    default_video_resolution: str = "best"


class HealthResponse(BaseModel):
    healthy: bool
    download_dir_writable: bool
    config_dir_writable: bool
    yt_dlp: str
    ffmpeg: str
    queue_concurrency: int
    auth_configured: bool


class DependencyUpdateResponse(BaseModel):
    yt_dlp: str
    ffmpeg: str
    yt_dlp_version: str | None = None
    ffmpeg_version: str | None = None
