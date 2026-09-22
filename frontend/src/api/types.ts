export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted';
export type MediaType = 'video' | 'audio' | 'subtitle' | 'other';
export type DownloadMode = 'video' | 'audio' | 'subtitles';
export type PlaylistEntryType = 'video' | 'multipart_video' | 'favorite_collection' | 'audio';

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

export type Platform = 'bilibili';
export type AccountState = 'valid' | 'invalid' | 'unknown' | 'expired';
export type AccountResourceType = 'created_favorite' | 'collected_favorite' | 'watch_later' | 'collection' | 'series';

export interface PlatformAccount {
  id: string;
  platform: Platform;
  label: string;
  external_id?: string | null;
  display_name?: string | null;
  avatar_url?: string | null;
  vip_type?: number | null;
  state: AccountState;
  cookie_status: CookieProfileStatus;
  login_method: 'cookie' | 'qr';
  auto_refresh: boolean;
  last_refresh_at?: string | null;
  last_refresh_check_at?: string | null;
  last_refresh_error?: string | null;
  is_default: boolean;
  last_verified_at?: string | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AccountCreateRequest {
  platform: Platform;
  label: string;
  cookie_content: string;
  make_default: boolean;
}

export interface AccountUpdateRequest {
  label?: string;
  cookie_content?: string;
  make_default?: boolean;
}

export interface BilibiliQrStartResponse {
  challenge_id: string;
  qr_url: string;
  expires_at: string;
}

export interface BilibiliQrPollResponse {
  status: 'pending' | 'scanned' | 'expired' | 'completed';
  message: string;
  account?: PlatformAccount | null;
}

export interface AccountResource {
  id: string;
  account_id: string;
  platform: Platform;
  resource_type: AccountResourceType;
  external_id: string;
  title: string;
  description?: string | null;
  cover_url?: string | null;
  owner_name?: string | null;
  owner_id?: string | null;
  item_count?: number | null;
  is_private: boolean;
  source_url: string;
  updated_at?: number | null;
}

export interface PageInfo {
  offset: number;
  limit: number;
  total: number;
  has_more: boolean;
}

export interface AccountResourceListResponse {
  items: AccountResource[];
  page: PageInfo;
}

export interface AccountResourceEntriesResponse {
  resource: AccountResource;
  entries: PlaylistEntry[];
  page: PageInfo;
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

export interface PlaylistEntryGroup {
  id: string;
  title: string;
  entry_type: Extract<PlaylistEntryType, 'favorite_collection' | 'multipart_video'>;
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
  is_available?: boolean;
  unavailable_reason?: string | null;
  entry_type?: PlaylistEntryType;
  item_count?: number | null;
  resource_id?: string | null;
  parent_id?: string | null;
  parent_title?: string | null;
  part_index?: number | null;
  part_count?: number | null;
  group_path?: PlaylistEntryGroup[];
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
  account_id?: string | null;
  playlist_items?: string | null;
  playlist_title?: string | null;
  playlist_entries: PlaylistEntry[];
  task_origin?: 'manual' | 'monitor_initial' | 'monitor_update';
  monitor_id?: string | null;
  monitor_detected_at?: string | null;
  monitor_new_item_count?: number | null;
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
  account_id?: string | null;
  download_options: CreateTaskRequest;
}

export interface PlaylistMonitorCreateResponse {
  monitor: PlaylistMonitorResponse;
  initial_task?: TaskResponse | null;
}

export interface PlaylistMonitorLog {
  id: number;
  monitor_id: string;
  timestamp: string;
  level: string;
  event: string;
  message: string;
  details: Record<string, unknown>;
}

export interface PlaylistMonitorLogListResponse {
  items: PlaylistMonitorLog[];
  page: PageInfo;
}

export interface PlaylistMonitorUpdate {
  enabled?: boolean | null;
  interval_minutes?: number | null;
}

export interface PlaylistMonitorResponse {
  id: string;
  url: string;
  account_id?: string | null;
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
