import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, createApiClient } from '../api/client';
import type { FileEntry, FileListResponse, HealthResponse, SettingsResponse, TaskEvent, TaskResponse } from '../api/types';
import { messages, type Locale, type T } from '../i18n';
import { AccountsPage } from '../pages/accounts/AccountsPage';
import { FilesPage } from '../pages/files/FilesPage';
import { HistoryPage } from '../pages/history/HistoryPage';
import { MonitorsPage } from '../pages/monitors/MonitorsPage';
import { PlayerPage } from '../pages/player/PlayerPage';
import { SettingsPage } from '../pages/settings/SettingsPage';
import { SystemPage } from '../pages/system/SystemPage';
import { TasksPage } from '../pages/tasks/TasksPage';
import { WorkspacePage } from '../pages/workspace/WorkspacePage';
import { initialWorkspaceState } from '../pages/workspace/workspaceState';
import { navItems, type Page } from './navigation';
import { TopBar } from './TopBar';

function upsertTask(tasks: TaskResponse[], nextTask: TaskResponse): TaskResponse[] {
  return tasks.some((task) => task.id === nextTask.id)
    ? tasks.map((task) => (task.id === nextTask.id ? nextTask : task))
    : [nextTask, ...tasks];
}

const assetBase = import.meta.env.BASE_URL;

export function App() {
  const [page, setPage] = useState<Page>(() => {
    const hash = window.location.hash.replace('#', '') as Page;
    return navItems.some(([id]) => id === hash) ? hash : 'workspace';
  });
  const [locale, setLocale] = useState<Locale>(() => (localStorage.getItem('ytsage.locale') as Locale) || 'zh');
  const [token, setToken] = useState(() => localStorage.getItem('ytsage.authToken') || '');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [workspaceState, setWorkspaceState] = useState(initialWorkspaceState);
  const [tasks, setTasks] = useState<TaskResponse[]>([]);
  const [historyRevision, setHistoryRevision] = useState(0);
  const [fileLibrary, setFileLibrary] = useState<FileListResponse | null>(null);
  const [playQueue, setPlayQueue] = useState<FileEntry[]>([]);
  const [currentFile, setCurrentFile] = useState<FileEntry | null>(null);
  const [playFolder, setPlayFolder] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);

  const t = useCallback<T>((key) => messages[locale][key], [locale]);
  const api = useMemo(() => createApiClient({ token }), [token]);
  const handleLoadError = useCallback((err: unknown) => {
    if (err instanceof ApiError && err.status === 401) setAuthRequired(true);
    setError(err instanceof Error ? err.message : String(err));
  }, []);

  const loadStatus = useCallback(async () => {
    setError(null);
    try {
      setHealth(await api.health());
      setAuthRequired(false);
    } catch (err) {
      handleLoadError(err);
    }
  }, [api, handleLoadError]);
  const loadSettings = useCallback(async () => {
    setError(null);
    try {
      setSettings(await api.settings());
      setAuthRequired(false);
    } catch (err) {
      handleLoadError(err);
    }
  }, [api, handleLoadError]);
  const loadTasks = useCallback(async () => {
    setError(null);
    try {
      setTasks(await api.tasks(0, 100));
      setAuthRequired(false);
    } catch (err) {
      handleLoadError(err);
    }
  }, [api, handleLoadError]);
  const refreshCurrentPage = useCallback(async () => {
    if (page === 'tasks') return loadTasks();
    if (page === 'accounts') return loadStatus();
    if (page === 'history') {
      setHistoryRevision((current) => current + 1);
      return;
    }
    if (page === 'settings') return loadSettings();
    if (page === 'system') return Promise.all([loadStatus(), loadSettings()]).then(() => undefined);
    return loadStatus();
  }, [page, loadTasks, loadSettings, loadStatus]);

  useEffect(() => {
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
    localStorage.setItem('ytsage.locale', locale);
  }, [locale]);
  useEffect(() => {
    void loadStatus();
    void loadSettings();
  }, [loadStatus, loadSettings]);
  useEffect(() => {
    if (page === 'tasks') void loadTasks();
    if (page === 'settings') void loadSettings();
    if (page === 'system') void Promise.all([loadStatus(), loadSettings()]);
  }, [page, loadTasks, loadSettings, loadStatus]);
  useEffect(() => {
    if (page !== 'tasks') return;
    const timer = window.setInterval(() => void loadTasks(), 8000);
    return () => window.clearInterval(timer);
  }, [page, loadTasks]);
  useEffect(() => {
    let socket: WebSocket | null = null;
    try {
      socket = new WebSocket(api.eventUrl());
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data) as TaskEvent;
        setTasks((current) => upsertTask(current, payload.task));
        if (payload.type === 'task_completed') {
          setFileLibrary(null);
          setHistoryRevision((current) => current + 1);
        }
      };
    } catch {
      socket = null;
    }
    return () => socket?.close();
  }, [api]);

  function changePage(next: Page) {
    setPage(next);
    window.location.hash = next;
  }
  function saveToken(value: string) {
    setToken(value);
    if (value) localStorage.setItem('ytsage.authToken', value);
    else localStorage.removeItem('ytsage.authToken');
  }
  function playFile(file: FileEntry, queue: FileEntry[], folder = '') {
    const playableQueue = queue.filter((item) => item.playable);
    setPlayQueue(playableQueue.length ? playableQueue : [file]);
    setCurrentFile(file);
    setPlayFolder(folder);
    changePage('player');
  }
  function openFilesPage() {
    setFileLibrary(null);
    changePage('files');
  }
  function analyzeHistoryUrl(url: string) {
    setWorkspaceState((current) => ({
      ...current,
      url,
      analysis: null,
      accountId: null,
      selectedFormat: null,
      selectedPlaylistIndexes: [],
      selectedSubtitleLangs: [],
    }));
    changePage('workspace');
  }
  function analyzeAccountResource(url: string, accountId: string) {
    setWorkspaceState((current) => ({
      ...current,
      url,
      analysis: null,
      accountId,
      selectedFormat: null,
      selectedPlaylistIndexes: [],
      selectedSubtitleLangs: [],
    }));
    changePage('workspace');
  }

  return <div className="shell">
    <aside className="sidebar glass-surface">
      <div className="brand"><img src={`${assetBase}assets/ytsage-wordmark.svg`} alt="YTSage" /><span className="brand-edition">Studio</span></div>
      <nav className="nav" aria-label="Primary">{navItems.map(([id, Icon, labelKey]) => <button key={id} className={page === id ? 'active' : ''} onClick={() => id === 'files' ? openFilesPage() : changePage(id)} title={t(labelKey)}><Icon className="nav-icon" aria-hidden="true" /><span className="nav-label">{t(labelKey)}</span></button>)}</nav>
      <div className="sidebar-status"><span className={`status-orb ${health?.healthy ? 'online' : 'attention'}`} /><span><strong>YTSage Server</strong><small>{health?.healthy ? t('healthy') : t('needsTools')}</small></span></div>
    </aside>
    <main className="main">
      <TopBar page={page} health={health} authRequired={authRequired} token={token} locale={locale} t={t} onLocale={setLocale} onToken={saveToken} onRefresh={refreshCurrentPage} error={error} />
      {page === 'workspace' && <WorkspacePage api={api} t={t} settings={settings} state={workspaceState} onState={setWorkspaceState} onTask={(task) => { setTasks((current) => upsertTask(current, task)); changePage('tasks'); }} />}
      {page === 'accounts' && <AccountsPage api={api} health={health} t={t} onAnalyze={analyzeAccountResource} onTask={(task) => { setTasks((current) => upsertTask(current, task)); changePage('tasks'); }} />}
      {page === 'tasks' && <TasksPage tasks={tasks} api={api} t={t} onChanged={loadTasks} onCancel={async (id) => { const updated = await api.cancelTask(id); setTasks((current) => upsertTask(current, updated)); }} />}
      {page === 'monitors' && <MonitorsPage api={api} t={t} />}
      {page === 'history' && <HistoryPage api={api} t={t} refreshKey={historyRevision} onOpenFiles={openFilesPage} onAnalyze={analyzeHistoryUrl} onTask={(task) => { setTasks((current) => upsertTask(current, task)); changePage('tasks'); }} />}
      {page === 'files' && <FilesPage library={fileLibrary} token={token} api={api} t={t} onLoaded={setFileLibrary} onPlay={playFile} />}
      {page === 'player' && <PlayerPage current={currentFile} queue={playQueue} folder={playFolder} token={token} api={api} t={t} onSelect={setCurrentFile} onQueue={setPlayQueue} onFolder={setPlayFolder} />}
      {page === 'settings' && <SettingsPage api={api} settings={settings} token={token} t={t} onToken={saveToken} onSaved={loadSettings} />}
      {page === 'system' && <SystemPage api={api} health={health} settings={settings} t={t} onChanged={refreshCurrentPage} />}
    </main>
  </div>;
}
