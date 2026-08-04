import type {
  AnalyzeResponse,
  CookieSaveResponse,
  CreateTaskRequest,
  FileListResponse,
  HealthResponse,
  HistoryEntry,
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

function headers(token: string, json = false): HeadersInit {
  const result: Record<string, string> = {};
  if (json) result['Content-Type'] = 'application/json';
  if (token) result.Authorization = `Bearer ${token}`;
  return result;
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body.detail) message = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch {
      const text = await response.text();
      if (text) message = text;
    }
    throw new ApiError(response.status, message);
  }
  return response.json() as Promise<T>;
}

export function createApiClient({ token }: ApiClientOptions) {
  return {
    health: () => fetch('/api/health', { headers: headers(token) }).then(parseResponse<HealthResponse>),
    settings: () => fetch('/api/settings', { headers: headers(token) }).then(parseResponse<SettingsResponse>),
    saveCookies: (content: string, profile = 'default') =>
      fetch('/api/settings/cookies', {
        method: 'POST',
        headers: headers(token, true),
        body: JSON.stringify({ content, profile }),
      }).then(parseResponse<CookieSaveResponse>),
    analyze: (url: string, genericMode = true) =>
      fetch('/api/analyze', {
        method: 'POST',
        headers: headers(token, true),
        body: JSON.stringify({ url, generic_mode: genericMode }),
      }).then(parseResponse<AnalyzeResponse>),
    tasks: () => fetch('/api/tasks', { headers: headers(token) }).then(parseResponse<TaskResponse[]>),
    createTask: (request: CreateTaskRequest) =>
      fetch('/api/tasks', {
        method: 'POST',
        headers: headers(token, true),
        body: JSON.stringify(request),
      }).then(parseResponse<TaskResponse>),
    cancelTask: (taskId: string) =>
      fetch(`/api/tasks/${taskId}/cancel`, { method: 'POST', headers: headers(token) }).then(parseResponse<TaskResponse>),
    deleteTask: (taskId: string) => fetch(`/api/tasks/${taskId}`, { method: 'DELETE', headers: headers(token) }).then((response) => {
      if (!response.ok) return parseResponse<never>(response);
    }),
    clearTasks: () => fetch('/api/tasks', { method: 'DELETE', headers: headers(token) }).then((response) => {
      if (!response.ok) return parseResponse<never>(response);
    }),
    history: () => fetch('/api/history', { headers: headers(token) }).then(parseResponse<HistoryEntry[]>),
    deleteHistory: (historyId: string) => fetch(`/api/history/${historyId}`, { method: 'DELETE', headers: headers(token) }).then((response) => {
      if (!response.ok) return parseResponse<never>(response);
    }),
    clearHistory: () => fetch('/api/history', { method: 'DELETE', headers: headers(token) }).then((response) => {
      if (!response.ok) return parseResponse<never>(response);
    }),
    files: (query = '', folder = '', offset = 0, limit = 50) => {
      const params = new URLSearchParams();
      if (query) params.set('q', query);
      if (folder) params.set('folder', folder);
      params.set('offset', String(offset));
      params.set('limit', String(limit));
      return fetch(`/api/files?${params.toString()}`, { headers: headers(token) }).then(parseResponse<FileListResponse>);
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
