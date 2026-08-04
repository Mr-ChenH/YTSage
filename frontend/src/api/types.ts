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

export interface SettingsResponse {
  download_dir: string;
  config_dir: string;
  queue_concurrency: number;
  auth_configured: boolean;
  cookies_configured: boolean;
  cookie_profiles: Record<string, boolean>;
}

export interface CookieSaveResponse {
  cookies_configured: boolean;
  profile: string;
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
  sponsorblock_categories: string[];
  rate_limit?: string | null;
  proxy_url?: string | null;
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
  playlist_current_index?: number | null;
  playlist_total?: number | null;
  playlist_failed_indexes?: number[];
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
