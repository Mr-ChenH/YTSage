import type {
  AccountCreateRequest,
  AccountResourceEntriesResponse,
  AccountResourceListResponse,
  AccountUpdateRequest,
  AnalyzeResponse,
  CookieSaveResponse,
  CreateTaskRequest,
  DependencyUpdateResponse,
  FileListResponse,
  HealthResponse,
  HistoryEntry,
  HistoryListResponse,
  PlaylistMonitorCreate,
  PlaylistMonitorCreateResponse,
  PlaylistMonitorResponse,
  PlaylistMonitorUpdate,
  PlatformAccount,
  SettingsResponse,
  TaskEvent,
  TaskResponse,
} from './types';

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export interface ApiClientOptions {
  token: string;
}

const pendingFileRequests = new Map<string, Promise<FileListResponse>>();
const pendingHistoryRequests = new Map<string, Promise<HistoryListResponse>>();
const pendingAccountRequests = new Map<string, Promise<PlatformAccount[]>>();
const pendingAccountResourceRequests = new Map<string, Promise<AccountResourceListResponse | AccountResourceEntriesResponse>>();

function headers(token: string, json = false): HeadersInit {
  const result: Record<string, string> = {};
  if (json) result['Content-Type'] = 'application/json';
  if (token) result.Authorization = `Bearer ${token}`;
  return result;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    const text = await response.text();
    if (text) {
      try {
        const body = JSON.parse(text) as { detail?: unknown };
        if (body.detail) {
          if (typeof body.detail === 'string') message = body.detail;
          else if (typeof body.detail === 'object' && body.detail && 'message' in body.detail) message = String((body.detail as { message: unknown }).message);
          else message = JSON.stringify(body.detail);
        }
        else message = text;
      } catch {
        message = text;
      }
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export function createApiClient({ token }: ApiClientOptions) {
  return {
    health: () => fetch('/api/health', { headers: headers(token) }).then(parseResponse<HealthResponse>),
    dependencyStatus: (refresh = false) => fetch(`/api/dependencies${refresh ? '?refresh=true' : ''}`, { headers: headers(token) }).then(parseResponse<DependencyUpdateResponse>),
    updateDependencies: () => fetch('/api/dependencies/update', { method: 'POST', headers: headers(token) }).then(parseResponse<DependencyUpdateResponse>),
    settings: () => fetch('/api/settings', { headers: headers(token) }).then(parseResponse<SettingsResponse>),
    saveCookies: (content: string, profile = 'default') =>
      fetch('/api/settings/cookies', {
        method: 'POST',
        headers: headers(token, true),
        body: JSON.stringify({ content, profile }),
      }).then(parseResponse<CookieSaveResponse>),
    saveFilenameTemplate: (filenameTemplate: string, defaultVideoResolution?: string) =>
      fetch('/api/settings/filename-template', {
        method: 'POST',
        headers: headers(token, true),
        body: JSON.stringify({ filename_template: filenameTemplate, default_video_resolution: defaultVideoResolution }),
      }).then(parseResponse<SettingsResponse>),
    accounts: () => {
      const pending = pendingAccountRequests.get(token);
      if (pending) return pending;
      const request = fetch('/api/accounts', { headers: headers(token) }).then(parseResponse<PlatformAccount[]>).finally(() => pendingAccountRequests.delete(token));
      pendingAccountRequests.set(token, request);
      return request;
    },
    accountAvatarUrl: (accountId: string) => `/api/accounts/${encodeURIComponent(accountId)}/avatar${token ? `?token=${encodeURIComponent(token)}` : ''}`,
    createAccount: (request: AccountCreateRequest) => fetch('/api/accounts', { method: 'POST', headers: headers(token, true), body: JSON.stringify(request) }).then(parseResponse<PlatformAccount>),
    updateAccount: (accountId: string, request: AccountUpdateRequest) => fetch(`/api/accounts/${accountId}`, { method: 'PATCH', headers: headers(token, true), body: JSON.stringify(request) }).then(parseResponse<PlatformAccount>),
    verifyAccount: (accountId: string) => fetch(`/api/accounts/${accountId}/verify`, { method: 'POST', headers: headers(token) }).then(parseResponse<PlatformAccount>),
    setDefaultAccount: (accountId: string) => fetch(`/api/accounts/${accountId}/default`, { method: 'POST', headers: headers(token) }).then(parseResponse<PlatformAccount>),
    deleteAccount: (accountId: string) => fetch(`/api/accounts/${accountId}`, { method: 'DELETE', headers: headers(token) }).then((response) => { if (!response.ok) return parseResponse<never>(response); }),
    accountResources: (accountId: string, kind = 'created_favorite', offset = 0, limit = 20) => {
      const params = new URLSearchParams({ kind, offset: String(offset), limit: String(limit) });
      const url = `/api/accounts/${accountId}/resources?${params}`;
      const key = `${token}\n${url}`;
      const pending = pendingAccountResourceRequests.get(key) as Promise<AccountResourceListResponse> | undefined;
      if (pending) return pending;
      const request = fetch(url, { headers: headers(token) }).then(parseResponse<AccountResourceListResponse>).finally(() => pendingAccountResourceRequests.delete(key));
      pendingAccountResourceRequests.set(key, request);
      return request;
    },
    accountResourceEntries: (accountId: string, resourceId: string, offset = 0, limit = 20) => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      const url = `/api/accounts/${accountId}/resources/${encodeURIComponent(resourceId)}/entries?${params}`;
      const key = `${token}\n${url}`;
      const pending = pendingAccountResourceRequests.get(key) as Promise<AccountResourceEntriesResponse> | undefined;
      if (pending) return pending;
      const request = fetch(url, { headers: headers(token) }).then(parseResponse<AccountResourceEntriesResponse>).finally(() => pendingAccountResourceRequests.delete(key));
      pendingAccountResourceRequests.set(key, request);
      return request;
    },
    analyze: (url: string, genericMode = true, accountId?: string | null) =>
      fetch('/api/analyze', {
        method: 'POST',
        headers: headers(token, true),
        body: JSON.stringify({ url, generic_mode: genericMode, account_id: accountId || null }),
      }).then(parseResponse<AnalyzeResponse>),
    tasks: (offset = 0, limit = 100, activeOnly = false) => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      if (activeOnly) params.set('active_only', 'true');
      return fetch(`/api/tasks?${params.toString()}`, { headers: headers(token) }).then(parseResponse<TaskResponse[]>);
    },
    createTask: (request: CreateTaskRequest) =>
      fetch('/api/tasks', {
        method: 'POST',
        headers: headers(token, true),
        body: JSON.stringify(request),
      }).then(parseResponse<TaskResponse>),
    monitors: () => fetch('/api/monitors', { headers: headers(token) }).then(parseResponse<PlaylistMonitorResponse[]>),
    createMonitor: (request: PlaylistMonitorCreate) =>
      fetch('/api/monitors', {
        method: 'POST',
        headers: headers(token, true),
        body: JSON.stringify(request),
      }).then(parseResponse<PlaylistMonitorCreateResponse>),
    updateMonitor: (monitorId: string, request: PlaylistMonitorUpdate) =>
      fetch(`/api/monitors/${monitorId}`, {
        method: 'PATCH',
        headers: headers(token, true),
        body: JSON.stringify(request),
      }).then(parseResponse<PlaylistMonitorResponse>),
    checkMonitor: (monitorId: string) =>
      fetch(`/api/monitors/${monitorId}/check`, { method: 'POST', headers: headers(token) }).then(parseResponse<PlaylistMonitorResponse>),
    deleteMonitor: (monitorId: string) => fetch(`/api/monitors/${monitorId}`, { method: 'DELETE', headers: headers(token) }).then((response) => {
      if (!response.ok) return parseResponse<never>(response);
    }),
    cancelTask: (taskId: string) =>
      fetch(`/api/tasks/${taskId}/cancel`, { method: 'POST', headers: headers(token) }).then(parseResponse<TaskResponse>),
    resumeTask: (taskId: string) =>
      fetch(`/api/tasks/${taskId}/resume`, { method: 'POST', headers: headers(token) }).then(parseResponse<TaskResponse>),
    restartTask: (taskId: string) =>
      fetch(`/api/tasks/${taskId}/restart`, { method: 'POST', headers: headers(token) }).then(parseResponse<TaskResponse>),
    retryPlaylistItem: (taskId: string, playlistIndex: number) =>
      fetch(`/api/tasks/${taskId}/retry-playlist-item/${playlistIndex}`, { method: 'POST', headers: headers(token) }).then(parseResponse<TaskResponse>),
    deleteTask: (taskId: string) => fetch(`/api/tasks/${taskId}`, { method: 'DELETE', headers: headers(token) }).then((response) => {
      if (!response.ok) return parseResponse<never>(response);
    }),
    clearTasks: () => fetch('/api/tasks', { method: 'DELETE', headers: headers(token) }).then((response) => {
      if (!response.ok) return parseResponse<never>(response);
    }),
    history: (offset = 0, limit = 50) => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      return fetch(`/api/history?${params.toString()}`, { headers: headers(token) }).then(parseResponse<HistoryEntry[]>);
    },
    searchHistory: (offset = 0, limit = 20, query = '', status = '', mediaType = '') => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(limit) });
      if (query) params.set('q', query);
      if (status) params.set('status', status);
      if (mediaType) params.set('media_type', mediaType);
      const url = `/api/history/search?${params.toString()}`;
      const requestKey = `${token}\n${url}`;
      const pending = pendingHistoryRequests.get(requestKey);
      if (pending) return pending;
      const request = fetch(url, { headers: headers(token) })
        .then(parseResponse<HistoryListResponse>)
        .finally(() => pendingHistoryRequests.delete(requestKey));
      pendingHistoryRequests.set(requestKey, request);
      return request;
    },
    redownloadHistory: (historyId: string) => fetch(`/api/history/${historyId}/redownload`, { method: 'POST', headers: headers(token) }).then(parseResponse<TaskResponse>),
    deleteHistory: (historyId: string) => fetch(`/api/history/${historyId}`, { method: 'DELETE', headers: headers(token) }).then((response) => {
      if (!response.ok) return parseResponse<never>(response);
    }),
    clearHistory: () => fetch('/api/history', { method: 'DELETE', headers: headers(token) }).then((response) => {
      if (!response.ok) return parseResponse<never>(response);
    }),
    files: (query = '', folder = '', offset = 0, limit = 50, mediaOnly = false, directOnly = false) => {
      const params = new URLSearchParams();
      if (query) params.set('q', query);
      if (folder) params.set('folder', folder);
      params.set('offset', String(offset));
      params.set('limit', String(limit));
      if (mediaOnly) params.set('media_only', 'true');
      if (directOnly) params.set('direct_only', 'true');
      const url = `/api/files?${params.toString()}`;
      const requestKey = `${token}\n${url}`;
      const pending = pendingFileRequests.get(requestKey);
      if (pending) return pending;
      const request = fetch(url, { headers: headers(token) })
        .then(parseResponse<FileListResponse>)
        .finally(() => pendingFileRequests.delete(requestKey));
      pendingFileRequests.set(requestKey, request);
      return request;
    },
    deleteFile: (fileId: string) => fetch(`/api/files/${encodeURIComponent(fileId)}`, {
      method: 'DELETE',
      headers: headers(token),
    }).then((response) => {
      if (!response.ok) return parseResponse<never>(response);
    }),
    deleteFolder: (folder: string) => {
      const params = new URLSearchParams({ folder });
      return fetch(`/api/folders?${params.toString()}`, {
        method: 'DELETE',
        headers: headers(token),
      }).then((response) => {
        if (!response.ok) return parseResponse<never>(response);
      });
    },
    downloadFolderUrl: (folder: string) => {
      const params = new URLSearchParams();
      if (folder) params.set('folder', folder);
      return `/api/folders/download?${params.toString()}`;
    },
    folderManifestUrl: (folder: string, format = 'aria2') => {
      const params = new URLSearchParams();
      if (folder) params.set('folder', folder);
      params.set('format', format);
      return `/api/folders/manifest?${params.toString()}`;
    },
    eventUrl: () => {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const query = token ? `?token=${encodeURIComponent(token)}` : '';
      return `${protocol}//${window.location.host}/api/events${query}`;
    },
    withAuthUrl: (url: string) => url,
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;
export type { TaskEvent };
