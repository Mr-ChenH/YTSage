export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
export type MediaType = 'video' | 'audio' | 'subtitle' | 'other';
export type DownloadMode = 'video' | 'audio' | 'subtitles';

export interface HealthResponse {
  healthy: boolean;
  download_dir_writable: boolean;
  config_dir_writable: boolean;
  yt_dlp: string;
  ffmpeg: string;
  queue_concurrency: number;
  auth_configured: boolean;
}

export interface DependencyStatus {
  name: string;
  current_version?: string | null;
  latest_version?: string | null;
  update_available: boolean;
  managed: boolean;
  source?: string | null;
  error?: string | null;
}

export interface DependencyUpdateResponse {
  running: boolean;
  phase: 'idle' | 'checking' | 'ready' | 'updating' | 'completed' | 'failed';
  dependencies: DependencyStatus[];
  logs: string[];
  error?: string | null;
}

export type CookieState = 'not_configured' | 'valid' | 'session' | 'expiring' | 'expired' | 'invalid';
export type CookieLoginState = 'valid' | 'invalid' | 'unknown';

export interface CookieProfileStatus {
  state: CookieState;
  configured: boolean;
  usable: boolean;
  total_count: number;
  valid_count: number;
  expired_count: number;
  session_count: number;
  earliest_expiry?: number | null;
  login_state?: CookieLoginState | null;
  login_checked_at?: number | null;
}

export interface SettingsResponse {
  download_dir: string;
  config_dir: string;
  queue_concurrency: number;
  auth_configured: boolean;
  cookies_configured: boolean;
  cookie_profiles: Record<string, boolean>;
  cookie_profile_status: Record<string, CookieProfileStatus>;
  filename_template: string;
  default_video_resolution: string;
}

export interface CookieSaveResponse {
  cookies_configured: boolean;
  profile: string;
  status?: CookieProfileStatus | null;
}

export interface FormatInfo {
  format_id: string;
  ext?: string | null;
  resolution?: string | null;
  video_codec?: string | null;
  audio_codec?: string | null;
  fps?: number | null;
  filesize?: number | null;
  type: string;
}

export interface SubtitleInfo {
  language: string;
  name?: string | null;
  automatic: boolean;
  formats: string[];
}

export interface PlaylistEntry {
  index: number;
  id?: string | null;
  title?: string | null;
  url?: string | null;
  webpage_url?: string | null;
  duration?: number | null;
  channel?: string | null;
  thumbnail_url?: string | null;
}

export interface AnalyzeResponse {
  url: string;
  title?: string | null;
  channel?: string | null;
  duration?: number | null;
  thumbnail_url?: string | null;
  is_playlist: boolean;
  playlist_count?: number | null;
  playlist_entries: PlaylistEntry[];
  formats: FormatInfo[];
  subtitles: SubtitleInfo[];
  raw: Record<string, unknown>;
}

export interface CreateTaskRequest {
  url: string;
  mode: DownloadMode;
  format_id?: string | null;
  output_format: string;
  audio_format: string;
  subtitle_langs: string[];
  merge_subtitles: boolean;
  save_thumbnail: boolean;
  save_description: boolean;
  embed_chapters: boolean;
  audio_normalization: boolean;
  rate_limit?: string | null;
  proxy_url?: string | null;
  concurrent_fragments?: number | null;
  cookie_file?: string | null;
  playlist_items?: string | null;
  playlist_title?: string | null;
  playlist_entries: PlaylistEntry[];
  filename_template: string;
}

export interface TaskProgress {
  percent?: number | null;
  status_text?: string | null;
  speed?: string | null;
  eta?: string | null;
  current_filename?: string | null;
  downloaded_bytes?: number | null;
  total_bytes?: number | null;
  playlist_current_index?: number | null;
  playlist_last_index?: number | null;
  playlist_total?: number | null;
  playlist_failed_indexes?: number[];
  playlist_completed_indexes?: number[];
  playlist_failures?: Record<string, string>;
}

export interface TaskResponse {
  id: string;
  url: string;
  mode: DownloadMode;
  status: TaskStatus;
  options: Record<string, unknown>;
  progress: TaskProgress;
  error?: string | null;
  output_path?: string | null;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface TaskEvent {
  type: string;
  task: TaskResponse;
}

export interface HistoryEntry {
  id: string;
  task_id?: string | null;
  url?: string | null;
  title?: string | null;
  output_path?: string | null;
  file_size?: number | null;
  media_type: MediaType;
  status: string;
  downloaded_at: string;
  metadata: Record<string, unknown>;
}

export interface HistoryListResponse {
  items: HistoryEntry[];
  total: number;
  offset: number;
  limit: number;
}

export interface PlaylistMonitorCreate {
  url: string;
  interval_minutes: number;
  download_options: CreateTaskRequest;
}

export interface PlaylistMonitorCreateResponse {
  monitor: PlaylistMonitorResponse;
  initial_task: TaskResponse;
}

export interface PlaylistMonitorUpdate {
  enabled?: boolean | null;
  interval_minutes?: number | null;
}

export interface PlaylistMonitorResponse {
  id: string;
  url: string;
  title?: string | null;
  enabled: boolean;
  interval_minutes: number;
  download_options: Record<string, unknown>;
  seen_entry_keys: string[];
  last_checked_at?: string | null;
  next_check_at: string;
  last_error?: string | null;
  last_task_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface FileEntry {
  id: string;
  name: string;
  relative_path: string;
  size: number;
  modified_at: string;
  media_type: MediaType;
  playable: boolean;
  download_url: string;
  stream_url?: string | null;
}

export interface FileListResponse {
  root: string;
  files: FileEntry[];
  folders: string[];
  total: number;
  offset: number;
  limit: number;
  query?: string | null;
  folder?: string | null;
}
