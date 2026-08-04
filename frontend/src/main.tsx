import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Artplayer from 'artplayer';
import { createRoot } from 'react-dom/client';
import { ApiError, createApiClient } from './api/client';
import type {
  AnalyzeResponse,
  CreateTaskRequest,
  DownloadMode,
  FileEntry,
  FileListResponse,
  FormatInfo,
  HealthResponse,
  HistoryEntry,
  MediaType,
  PlaylistEntry,
  SettingsResponse,
  TaskEvent,
  TaskResponse,
  TaskStatus,
} from './api/types';
import './styles.css';

const messages = {
  zh: {
    navWorkspace: '下载',
    navTasks: '任务',
    navHistory: '历史',
    navFiles: '文件',
    navPlayer: '播放',
    navSettings: '设置',
    navSystem: '系统',
    workspaceTitle: '下载工作台',
    workspaceDesc: '分析链接、选择格式，并加入下载队列。',
    tasksTitle: '任务',
    tasksDesc: '通过 WebSocket 和轮询同步队列与实时进度。',
    historyTitle: '历史',
    historyDesc: '查看已完成和失败的下载记录。',
    filesTitle: '文件',
    filesDesc: '下载目录文件库，提供安全链接和支持 Range 的播放。',
    playerTitle: '播放',
    playerDesc: '播放下载目录中的视频和音频文件。',
    settingsTitle: '设置',
    settingsDesc: '服务端默认值和可选 Token 辅助配置。',
    systemTitle: '系统',
    systemDesc: '容器、依赖和存储健康状态。',
    healthy: '健康',
    needsTools: '缺少工具',
    tokenRequired: '需要 Token',
    noToken: '未配置 Token',
    bearerToken: 'Bearer Token',
    refresh: '刷新',
    analyzeUrl: '分析链接',
    formatsCount: '个格式',
    urlPlaceholder: '粘贴 YouTube 或 yt-dlp 支持的链接',
    paste: '粘贴',
    analyze: '分析',
    working: '处理中...',
    analyzeEmpty: '分析一个链接后预览元数据、格式和字幕。',
    untitled: '未命名媒体',
    unknownChannel: '未知频道',
    minutes: '分钟',
    formatsReady: '格式就绪',
    analyzeWarning: '解析提示',
    sourcePage: '来源页面',
    extractor: '提取器',
    originalUrl: '原始链接',
    fallbackFormats: '未返回具体格式，已提供通用下载选项',
    metadataWithoutFormats: 'yt-dlp 只返回了标题等元数据，没有返回具体视频格式。这常见于年龄限制、风险确认、需要登录的页面，或该站点只在下载阶段解析格式。已提供 best 和 bestaudio 通用下载选项；如果下载仍失败，需要为该站点配置 cookies。',
    subtitles: '字幕',
    playlist: '播放列表',
    pick: '选择',
    type: '类型',
    resolution: '分辨率',
    ext: '扩展名',
    video: '视频',
    audio: '音频',
    fps: '帧率',
    size: '大小',
    id: 'ID',
    downloadOptions: '下载选项',
    queued: '已排队',
    modeVideo: '视频',
    modeAudio: '音频',
    modeSubtitles: '字幕',
    videoOutputFormat: '视频输出格式',
    subtitleLanguages: '字幕语言',
    proxyUrl: '代理地址',
    proxyPlaceholder: '例如 http://127.0.0.1:7890',
    concurrentFragments: '并发片段',
    defaultVideoResolution: '默认视频清晰度',
    audioOutputFormat: '音频输出格式',
    formatSelect: '格式选择',
    autoBestFormat: '自动选择最佳格式',
    playlistSelection: '播放列表选择',
    analysisPlaylistTab: '视频列表',
    analysisFormatsTab: '格式列表',
    rowsPerPage: '每页',
    selectedItemsCount: '已选择',
    allItems: '全部条目',
    clearItems: '清空',
    playlistIndex: '序号',
    title: '标题',
    channel: '频道',
    duration: '时长',
    best: 'best',
    mergeSubtitles: '合并字幕',
    saveThumbnail: '保存缩略图',
    saveDescription: '保存描述',
    embedChapters: '嵌入章节',
    normalizeAudio: '音频标准化',
    createTask: '创建下载任务',
    noTasks: '暂无任务。请从下载工作台创建下载。',
    taskPlaylist: '下载列表',
    expand: '展开',
    collapse: '折叠',
    currentItem: '当前',
    clearRecords: '清空记录',
    deleteRecord: '删除记录',
    confirmClearTasks: '确认清空已结束的任务记录？正在运行或排队的任务会保留。',
    confirmClearHistory: '确认清空全部历史记录？不会删除下载文件。',
    cancel: '取消',
    openFiles: '打开文件',
    redownload: '重新下载',
    retryItem: '重试',
    copyPath: '复制路径',
    noHistory: '暂无历史。完成的下载会显示在这里。',
    library: '文件库',
    searchFiles: '按文件名搜索',
    folderFilter: '文件夹',
    folderTree: '目录树',
    mediaInFolder: '媒体文件',
    directMediaOnly: '显示当前目录下的视频和音频',
    allFolders: '全部文件夹',
    downloadFolder: '下载 ZIP',
    downloadManifest: '下载清单',
    previousPage: '上一页',
    nextPage: '下一页',
    jumpToPage: '跳转',
    pageNumber: '页码',
    pageInfo: '第 {page} / {pages} 页，共 {total} 个文件',
    search: '搜索',
    noFiles: '下载目录下暂无文件。',
    playable: '可播放',
    play: '播放',
    download: '下载',
    copyLink: '复制链接',
    player: '播放器',
    playQueue: '播放列表',
    playerFolder: '播放目录',
    speed: '倍速',
    selectPlayable: '请选择一个可播放文件。',
    downloadOnly: '此格式仅支持下载。',
    downloadDir: '下载目录',
    filenameTemplate: '文件保存格式',
    filenameTemplatePreset: '保存格式预设',
    filenameTemplateCustom: '自定义保存格式',
    filenameTemplateDescTitle: '仅标题，最简洁',
    filenameTemplateDescTitleId: '标题 + 视频 ID，避免重名',
    filenameTemplateDescResolutionId: '标题 + 分辨率 + 视频 ID，适合视频文件',
    filenameTemplateDescDateTitleId: '上传日期 + 标题 + 视频 ID，适合按时间整理',
    filenameTemplateDescUploaderTitleId: '按作者分文件夹保存',
    filenameTemplateDescCustom: '手动编辑 yt-dlp 输出模板',
    filenameTemplateSaved: '文件保存格式已保存',
    configDir: '配置目录',
    queueConcurrency: '队列并发',
    authConfigured: '服务端认证',
    optionalAuthToken: '可选认证 Token',
    cookieFile: 'Cookies 文件',
    cookiePaste: '粘贴 Cookies',
    cookiePastePlaceholder: '粘贴 Netscape cookies.txt 内容，或浏览器扩展导出的 JSON cookies 内容',
    uploadCookieFile: '上传 Cookies 文件',
    saveCookies: '保存 Cookies',
    saveSettings: '保存设置',
    clearCookies: '清除 Cookies',
    cookiesConfigured: 'Cookies 状态',
    cookieProfile: 'Cookies 平台',
    cookieProfileDefault: '默认',
    cookieProfileBilibili: '哔哩哔哩',
    cookieProfileYoutube: 'YouTube',
    cookiesSaved: 'Cookies 已保存',
    cookiesCleared: 'Cookies 已清除',
    configured: '已配置',
    notConfigured: '未配置',
    yes: '是',
    no: '否',
    needsAttention: '需要处理',
    api: 'API',
    fastapiServer: 'FastAPI 服务端',
    requiredAnalyze: '分析/下载所需',
    requiredMuxing: '封装/转换所需',
    updateDependencies: '更新依赖',
    dependenciesUpdated: '依赖已更新',
    serverDetails: '服务端详情',
    stdout: '标准输出',
    unknown: '未知',
    statusQueued: '排队中',
    statusRunning: '运行中',
    statusCompleted: '已完成',
    statusFailed: '失败',
    statusCancelled: '已取消',
    statusInterrupted: '已中断',
    itemPending: '未下载',
    itemDownloading: '正在下载',
    itemCompleted: '已下载',
    itemFailed: '错误',
    mediaVideo: '视频',
    mediaAudio: '音频',
    mediaSubtitle: '字幕',
    mediaOther: '其他',
    language: '语言',
    chinese: '中文',
    english: 'English',
  },
  en: {
    navWorkspace: 'Download',
    navTasks: 'Tasks',
    navHistory: 'History',
    navFiles: 'Files',
    navPlayer: 'Player',
    navSettings: 'Settings',
    navSystem: 'System',
    workspaceTitle: 'Download Workspace',
    workspaceDesc: 'Analyze, choose formats, and send work into the queue.',
    tasksTitle: 'Tasks',
    tasksDesc: 'Realtime queue and progress, updated through WebSocket and polling.',
    historyTitle: 'History',
    historyDesc: 'Completed and failed task records.',
    filesTitle: 'Files',
    filesDesc: 'Download-root library with safe links and Range-capable playback.',
    playerTitle: 'Player',
    playerDesc: 'Play video and audio files from the download directory.',
    settingsTitle: 'Settings',
    settingsDesc: 'Server-side defaults and optional token helper.',
    systemTitle: 'System',
    systemDesc: 'Container, dependency, and storage health.',
    healthy: 'Healthy',
    needsTools: 'Needs tools',
    tokenRequired: 'Token required',
    noToken: 'No token',
    bearerToken: 'Bearer token',
    refresh: 'Refresh',
    analyzeUrl: 'Analyze URL',
    formatsCount: 'formats',
    urlPlaceholder: 'Paste a YouTube or yt-dlp supported URL',
    paste: 'Paste',
    analyze: 'Analyze',
    working: 'Working...',
    analyzeEmpty: 'Analyze a URL to preview metadata, formats, and subtitles.',
    untitled: 'Untitled media',
    unknownChannel: 'Unknown channel',
    minutes: 'min',
    formatsReady: 'Formats ready',
    analyzeWarning: 'Analyze notice',
    sourcePage: 'Source page',
    extractor: 'Extractor',
    originalUrl: 'Original URL',
    fallbackFormats: 'No concrete formats returned; generic download selectors are available',
    metadataWithoutFormats: 'yt-dlp returned metadata without a concrete format list. This can happen for age-restricted/risk-confirmation pages, login-only media, or extractors that defer formats until download. Fallback format selectors are provided. If download still fails, configure cookies for this site.',
    subtitles: 'Subtitles',
    playlist: 'Playlist',
    pick: 'Pick',
    type: 'Type',
    resolution: 'Resolution',
    ext: 'Ext',
    video: 'Video',
    audio: 'Audio',
    fps: 'FPS',
    size: 'Size',
    id: 'ID',
    downloadOptions: 'Download Options',
    queued: 'queued',
    modeVideo: 'Video',
    modeAudio: 'Audio',
    modeSubtitles: 'Subtitles',
    videoOutputFormat: 'Video output format',
    subtitleLanguages: 'Subtitle languages',
    proxyUrl: 'Proxy URL',
    proxyPlaceholder: 'e.g. http://127.0.0.1:7890',
    concurrentFragments: 'Concurrent fragments',
    defaultVideoResolution: 'Default video resolution',
    audioOutputFormat: 'Audio output format',
    formatSelect: 'Format',
    autoBestFormat: 'Auto best format',
    playlistSelection: 'Playlist Selection',
    analysisPlaylistTab: 'Videos',
    analysisFormatsTab: 'Formats',
    rowsPerPage: 'Rows',
    selectedItemsCount: 'selected',
    allItems: 'All items',
    clearItems: 'Clear',
    playlistIndex: 'Index',
    title: 'Title',
    channel: 'Channel',
    duration: 'Duration',
    best: 'best',
    mergeSubtitles: 'Merge subtitles',
    saveThumbnail: 'Save thumbnail',
    saveDescription: 'Save description',
    embedChapters: 'Embed chapters',
    normalizeAudio: 'Normalize audio',
    createTask: 'Create Download Task',
    noTasks: 'No tasks yet. Create a download from the workspace.',
    taskPlaylist: 'Download list',
    expand: 'Expand',
    collapse: 'Collapse',
    currentItem: 'Current',
    clearRecords: 'Clear records',
    deleteRecord: 'Delete record',
    confirmClearTasks: 'Clear finished task records? Running and queued tasks will be kept.',
    confirmClearHistory: 'Clear all history records? Downloaded files will not be deleted.',
    cancel: 'Cancel',
    openFiles: 'Open Files',
    redownload: 'Redownload',
    retryItem: 'Retry',
    copyPath: 'Copy Path',
    noHistory: 'No history yet. Completed downloads will appear here.',
    library: 'Library',
    searchFiles: 'Search by filename',
    folderFilter: 'Folder',
    folderTree: 'Folders',
    mediaInFolder: 'Media files',
    directMediaOnly: 'Showing video and audio in the selected folder',
    allFolders: 'All folders',
    downloadFolder: 'Download ZIP',
    downloadManifest: 'Download Manifest',
    previousPage: 'Previous',
    nextPage: 'Next',
    jumpToPage: 'Go',
    pageNumber: 'Page',
    pageInfo: 'Page {page} / {pages}, {total} files',
    search: 'Search',
    noFiles: 'No files under the downloads root.',
    playable: 'Playable',
    play: 'Play',
    download: 'Download',
    copyLink: 'Copy Link',
    player: 'Player',
    playQueue: 'Playlist',
    playerFolder: 'Playback folder',
    speed: 'Speed',
    selectPlayable: 'Select a playable file.',
    downloadOnly: 'This format is download-only.',
    downloadDir: 'Download directory',
    filenameTemplate: 'Filename template',
    filenameTemplatePreset: 'Template preset',
    filenameTemplateCustom: 'Custom template',
    filenameTemplateDescTitle: 'Title only, shortest format',
    filenameTemplateDescTitleId: 'Title + video ID to avoid duplicate names',
    filenameTemplateDescResolutionId: 'Title + resolution + video ID, useful for video files',
    filenameTemplateDescDateTitleId: 'Upload date + title + video ID, useful for chronological folders',
    filenameTemplateDescUploaderTitleId: 'Save under uploader folders',
    filenameTemplateDescCustom: 'Manually edit the yt-dlp output template',
    filenameTemplateSaved: 'Filename template saved',
    configDir: 'Config directory',
    queueConcurrency: 'Queue concurrency',
    authConfigured: 'Auth configured',
    optionalAuthToken: 'Optional auth token',
    cookieFile: 'Cookies file',
    cookiePaste: 'Paste cookies',
    cookiePastePlaceholder: 'Paste Netscape cookies.txt content, or JSON cookies exported from a browser extension',
    uploadCookieFile: 'Upload cookies file',
    saveCookies: 'Save cookies',
    saveSettings: 'Save settings',
    clearCookies: 'Clear cookies',
    cookiesConfigured: 'Cookies status',
    cookieProfile: 'Cookies platform',
    cookieProfileDefault: 'Default',
    cookieProfileBilibili: 'Bilibili',
    cookieProfileYoutube: 'YouTube',
    cookiesSaved: 'Cookies saved',
    cookiesCleared: 'Cookies cleared',
    configured: 'Configured',
    notConfigured: 'Not configured',
    yes: 'yes',
    no: 'no',
    needsAttention: 'Needs attention',
    api: 'API',
    fastapiServer: 'FastAPI server',
    requiredAnalyze: 'Required for analyze/download',
    requiredMuxing: 'Required for muxing/conversion',
    updateDependencies: 'Update dependencies',
    dependenciesUpdated: 'Dependencies updated',
    serverDetails: 'Server Details',
    stdout: 'stdout',
    unknown: 'unknown',
    statusQueued: 'Queued',
    statusRunning: 'Running',
    statusCompleted: 'Completed',
    statusFailed: 'Failed',
    statusCancelled: 'Cancelled',
    statusInterrupted: 'Interrupted',
    itemPending: 'Pending',
    itemDownloading: 'Downloading',
    itemCompleted: 'Downloaded',
    itemFailed: 'Error',
    mediaVideo: 'Video',
    mediaAudio: 'Audio',
    mediaSubtitle: 'Subtitle',
    mediaOther: 'Other',
    language: 'Language',
    chinese: '中文',
    english: 'English',
  },
} as const;

type Locale = keyof typeof messages;
type TKey = keyof typeof messages.zh;
type T = (key: TKey) => string;

const navItems = [
  ['workspace', 'D', 'navWorkspace'],
  ['tasks', 'Q', 'navTasks'],
  ['history', 'H', 'navHistory'],
  ['files', 'F', 'navFiles'],
  ['player', 'P', 'navPlayer'],
  ['settings', 'S', 'navSettings'],
  ['system', 'I', 'navSystem'],
] as const;

type Page = (typeof navItems)[number][0];

function formatBytes(value?: number | null): string {
  if (!value) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function formatPageInfo(template: string, page: number, pages: number, total: number): string {
  return template.replace('{page}', String(page)).replace('{pages}', String(pages)).replace('{total}', String(total));
}

function statusTone(status?: string): string {
  if (status === 'completed') return 'green';
  if (status === 'running') return 'blue';
  if (status === 'queued') return 'amber';
  if (status === 'failed' || status === 'cancelled' || status === 'interrupted') return 'red';
  return '';
}

function statusLabel(status: TaskStatus | string, t: T): string {
  const labels: Record<string, TKey> = {
    queued: 'statusQueued',
    running: 'statusRunning',
    completed: 'statusCompleted',
    failed: 'statusFailed',
    cancelled: 'statusCancelled',
    interrupted: 'statusInterrupted',
  };
  return labels[status] ? t(labels[status]) : status;
}

function mediaLabel(mediaType: MediaType, t: T): string {
  const labels: Record<MediaType, TKey> = {
    video: 'mediaVideo',
    audio: 'mediaAudio',
    subtitle: 'mediaSubtitle',
    other: 'mediaOther',
  };
  return t(labels[mediaType]);
}

function fileDirectory(file: FileEntry): string {
  const normalized = file.relative_path.replaceAll('\\', '/');
  const suffix = `/${file.name}`;
  if (normalized === file.name) return '';
  if (normalized.endsWith(suffix)) return normalized.slice(0, -suffix.length);
  const index = normalized.lastIndexOf('/');
  return index >= 0 ? normalized.slice(0, index) : '';
}

function playlistMeta(file: FileEntry, t: T): string {
  const directory = fileDirectory(file);
  return directory ? `${directory} - ${formatBytes(file.size)}` : `${mediaLabel(file.media_type, t)} - ${formatBytes(file.size)}`;
}

function directParent(relativePath: string): string {
  const normalized = relativePath.replaceAll('\\', '/');
  const index = normalized.lastIndexOf('/');
  return index >= 0 ? normalized.slice(0, index) : '';
}

function modeLabel(mode: DownloadMode, t: T): string {
  const labels: Record<DownloadMode, TKey> = {
    video: 'modeVideo',
    audio: 'modeAudio',
    subtitles: 'modeSubtitles',
  };
  return t(labels[mode]);
}

function upsertTask(tasks: TaskResponse[], nextTask: TaskResponse): TaskResponse[] {
  const exists = tasks.some((task) => task.id === nextTask.id);
  if (!exists) return [nextTask, ...tasks];
  return tasks.map((task) => (task.id === nextTask.id ? nextTask : task));
}

function App() {
  const [page, setPage] = useState<Page>(() => {
    const hash = window.location.hash.replace('#', '') as Page;
    return navItems.some(([id]) => id === hash) ? hash : 'workspace';
  });
  const [locale, setLocale] = useState<Locale>(() => (localStorage.getItem('ytsage.locale') as Locale) || 'zh');
  const [token, setToken] = useState(() => localStorage.getItem('ytsage.authToken') || '');
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [tasks, setTasks] = useState<TaskResponse[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [fileLibrary, setFileLibrary] = useState<FileListResponse | null>(null);
  const [playQueue, setPlayQueue] = useState<FileEntry[]>([]);
  const [currentFile, setCurrentFile] = useState<FileEntry | null>(null);
  const [playFolder, setPlayFolder] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [authRequired, setAuthRequired] = useState(false);

  const t = useCallback<T>((key) => messages[locale][key], [locale]);
  const api = useMemo(() => createApiClient({ token }), [token]);

  const loadCore = useCallback(async () => {
    setError(null);
    try {
      const [healthData, settingsData, taskData, historyData] = await Promise.all([
        api.health(),
        api.settings(),
        api.tasks(),
        api.history(),
      ]);
      setHealth(healthData);
      setSettings(settingsData);
      setTasks(taskData);
      setHistory(historyData);
      setAuthRequired(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setAuthRequired(true);
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [api]);

  useEffect(() => {
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
    localStorage.setItem('ytsage.locale', locale);
  }, [locale]);

  useEffect(() => {
    void loadCore();
    const timer = window.setInterval(() => void loadCore(), 8000);
    return () => window.clearInterval(timer);
  }, [loadCore]);

  useEffect(() => {
    let socket: WebSocket | null = null;
    try {
      socket = new WebSocket(api.eventUrl());
      socket.onmessage = (event) => {
        const payload = JSON.parse(event.data) as TaskEvent;
        setTasks((current) => upsertTask(current, payload.task));
        if (payload.type === 'task_completed') {
          setFileLibrary(null);
          void loadCore();
        }
      };
    } catch {
      socket = null;
    }
    return () => socket?.close();
  }, [api, loadCore]);

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

  return (
    <div className="shell">
      <aside className="sidebar acrylic">
        <div className="brand">
          <img src="/static/assets/ytsage-wordmark.svg" alt="YTSage" />
        </div>
        <nav className="nav" aria-label="Primary">
          {navItems.map(([id, icon, labelKey]) => (
            <button key={id} className={page === id ? 'active' : ''} onClick={() => id === 'files' ? openFilesPage() : changePage(id)}>
              <span className="nav-icon">{icon}</span><span className="nav-label">{t(labelKey)}</span>
            </button>
          ))}
        </nav>
      </aside>

      <main className="main">
        <TopBar page={page} health={health} authRequired={authRequired} token={token} locale={locale} t={t} onLocale={setLocale} onToken={saveToken} onRefresh={loadCore} error={error} />
        {page === 'workspace' && <Workspace api={api} t={t} settings={settings} onTask={(task) => { setTasks((current) => upsertTask(current, task)); changePage('tasks'); }} />}
        {page === 'tasks' && <Tasks tasks={tasks} api={api} t={t} onChanged={loadCore} onCancel={async (id) => { const updated = await api.cancelTask(id); setTasks((current) => upsertTask(current, updated)); }} />}
        {page === 'history' && <History entries={history} api={api} t={t} onChanged={loadCore} onOpenFiles={openFilesPage} />}
        {page === 'files' && <Files library={fileLibrary} token={token} api={api} t={t} onLoaded={setFileLibrary} onPlay={playFile} />}
        {page === 'player' && <PlayerPage current={currentFile} queue={playQueue} folder={playFolder} token={token} api={api} t={t} onSelect={setCurrentFile} onQueue={setPlayQueue} onFolder={setPlayFolder} />}
        {page === 'settings' && <Settings api={api} settings={settings} token={token} t={t} onToken={saveToken} onSaved={loadCore} />}
        {page === 'system' && <System api={api} health={health} settings={settings} t={t} onChanged={loadCore} />}
      </main>
    </div>
  );
}

function TopBar({ page, health, authRequired, token, locale, t, onLocale, onToken, onRefresh, error }: {
  page: Page;
  health: HealthResponse | null;
  authRequired: boolean;
  token: string;
  locale: Locale;
  t: T;
  onLocale: (value: Locale) => void;
  onToken: (value: string) => void;
  onRefresh: () => void;
  error: string | null;
}) {
  const titles: Record<Page, [TKey, TKey]> = {
    workspace: ['workspaceTitle', 'workspaceDesc'],
    tasks: ['tasksTitle', 'tasksDesc'],
    history: ['historyTitle', 'historyDesc'],
    files: ['filesTitle', 'filesDesc'],
    player: ['playerTitle', 'playerDesc'],
    settings: ['settingsTitle', 'settingsDesc'],
    system: ['systemTitle', 'systemDesc'],
  };
  return (
    <div className="topbar">
      <div className="stack">
        <h1>{t(titles[page][0])}</h1>
        <p className="muted">{t(titles[page][1])}</p>
        {error && <p className="error-line">{error}</p>}
      </div>
      <div className="toolbar">
        <label className="language-label">
          <span>{t('language')}</span>
          <select className="language-select" value={locale} onChange={(event) => onLocale(event.target.value as Locale)}>
            <option value="zh">{t('chinese')}</option>
            <option value="en">{t('english')}</option>
          </select>
        </label>
        <span className="pill"><span className={`dot ${health?.healthy ? '' : 'amber'}`} />{health?.healthy ? t('healthy') : t('needsTools')}</span>
        <span className="pill"><span className={`dot ${health?.auth_configured || authRequired ? 'amber' : 'blue'}`} />{health?.auth_configured || authRequired ? t('tokenRequired') : t('noToken')}</span>
        {(authRequired || token) && <input className="token-input" value={token} placeholder={t('bearerToken')} onChange={(event) => onToken(event.target.value)} />}
        <button onClick={onRefresh}>{t('refresh')}</button>
      </div>
    </div>
  );
}

function playlistItemsValue(selectedIndexes: number[], total?: number | null): string | null {
  if (!selectedIndexes.length) return null;
  const sorted = [...new Set(selectedIndexes)].sort((a, b) => a - b);
  if (total && sorted.length === total && sorted[0] === 1 && sorted[sorted.length - 1] === total) return null;
  const ranges: string[] = [];
  let start = sorted[0];
  let previous = sorted[0];
  for (const index of sorted.slice(1)) {
    if (index === previous + 1) {
      previous = index;
      continue;
    }
    ranges.push(start === previous ? String(start) : `${start}-${previous}`);
    start = index;
    previous = index;
  }
  ranges.push(start === previous ? String(start) : `${start}-${previous}`);
  return ranges.join(',');
}

function selectedPlaylistEntries(analysis: AnalyzeResponse | null, selectedIndexes: number[]): PlaylistEntry[] {
  if (!analysis?.playlist_entries.length) return [];
  const selected = new Set(selectedIndexes);
  return analysis.playlist_entries.filter((entry) => selected.has(entry.index));
}

const filenameTemplatePresets: Array<{ id: string; template: string; descKey: TKey }> = [
  { id: 'title', template: '%(title)s.%(ext)s', descKey: 'filenameTemplateDescTitle' },
  { id: 'title-id', template: '%(title)s_[%(id)s].%(ext)s', descKey: 'filenameTemplateDescTitleId' },
  { id: 'title-resolution-id', template: '%(title)s_%(resolution)s_[%(id)s].%(ext)s', descKey: 'filenameTemplateDescResolutionId' },
  { id: 'date-title-id', template: '%(upload_date)s_%(title)s_[%(id)s].%(ext)s', descKey: 'filenameTemplateDescDateTitleId' },
  { id: 'uploader-title-id', template: '%(uploader)s/%(title)s_[%(id)s].%(ext)s', descKey: 'filenameTemplateDescUploaderTitleId' },
];

const videoResolutionOptions = ['best', '2160p', '1440p', '1080p', '720p', '480p', '360p'];

function taskFilenameTemplate(baseTemplate: string, isPlaylist: boolean): string {
  if (!isPlaylist) return baseTemplate;
  if (baseTemplate.includes('%(playlist_title)') || baseTemplate.includes('%(playlist_index)')) return baseTemplate;
  return `%(playlist_title)s/%(playlist_index)02d-${baseTemplate}`;
}

function modeFormats(formats: FormatInfo[], mode: DownloadMode): FormatInfo[] {
  if (mode === 'audio') {
    const audioFormats = formats.filter((format) => format.type === 'audio' || format.format_id === 'bestaudio');
    return audioFormats.length ? audioFormats : formats.filter((format) => format.audio_codec && format.audio_codec !== 'none');
  }
  if (mode === 'video') {
    const videoFormats = formats.filter((format) => format.type === 'video+audio' || format.type === 'video' || format.format_id === 'best');
    return videoFormats.length ? videoFormats : formats;
  }
  return [];
}

function preferredFormatForMode(formats: FormatInfo[], mode: DownloadMode, defaultResolution = 'best'): string | null {
  if (mode === 'subtitles') return null;
  const candidates = modeFormats(formats, mode);
  if (mode === 'audio') return candidates.find((format) => format.format_id === 'bestaudio')?.format_id || candidates[0]?.format_id || null;
  if (defaultResolution !== 'best') {
    const resolutionNumber = Number(defaultResolution.replace(/p$/i, ''));
    const matched = candidates.find((format) => {
      const text = [format.resolution, format.format_id].filter(Boolean).join(' ');
      return text.includes(defaultResolution) || text.includes(String(resolutionNumber));
    });
    if (matched) return matched.format_id;
  }
  return candidates.find((format) => format.format_id === 'best')?.format_id || candidates[0]?.format_id || null;
}

function formatLabel(format: FormatInfo): string {
  const bits = [format.format_id, format.type, format.resolution, format.ext, format.video_codec, format.audio_codec]
    .filter(Boolean)
    .map(String);
  return bits.join(' / ');
}

function toggleListItem(list: string[], item: string): string[] {
  return list.includes(item) ? list.filter((value) => value !== item) : [...list, item].sort();
}

function Workspace({ api, t, settings, onTask }: { api: ReturnType<typeof createApiClient>; t: T; settings: SettingsResponse | null; onTask: (task: TaskResponse) => void }) {
  const [url, setUrl] = useState('');
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [selectedFormat, setSelectedFormat] = useState<string | null>(null);
  const [audioFormat, setAudioFormat] = useState('mp3');
  const [videoOutputFormat, setVideoOutputFormat] = useState('mp4');
  const [selectedSubtitleLangs, setSelectedSubtitleLangs] = useState<string[]>([]);
  const [mergeSubtitles, setMergeSubtitles] = useState(true);
  const [saveThumbnail, setSaveThumbnail] = useState(false);
  const [saveDescription, setSaveDescription] = useState(false);
  const [embedChapters, setEmbedChapters] = useState(true);
  const [audioNormalization, setAudioNormalization] = useState(false);
  const [proxyUrl, setProxyUrl] = useState('');
  const [concurrentFragments, setConcurrentFragments] = useState(4);
  const [selectedPlaylistIndexes, setSelectedPlaylistIndexes] = useState<number[]>([]);
  const [mode, setMode] = useState<DownloadMode>('video');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function analyze() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.analyze(url);
      setAnalysis(data);
      setSelectedFormat(preferredFormatForMode(data.formats, mode, settings?.default_video_resolution || 'best'));
      setSelectedPlaylistIndexes(data.playlist_entries.map((entry) => entry.index));
      setSelectedSubtitleLangs([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!analysis) return;
    setSelectedFormat(preferredFormatForMode(analysis.formats, mode, settings?.default_video_resolution || 'best'));
  }, [mode, analysis, settings?.default_video_resolution]);

  async function createTask() {
    setBusy(true);
    setError(null);
    const request: CreateTaskRequest = {
      url,
      mode,
      format_id: selectedFormat,
      output_format: videoOutputFormat,
      audio_format: audioFormat,
      subtitle_langs: selectedSubtitleLangs,
      merge_subtitles: mergeSubtitles,
      save_thumbnail: saveThumbnail,
      save_description: saveDescription,
      embed_chapters: embedChapters,
      audio_normalization: audioNormalization,
      proxy_url: proxyUrl.trim() || null,
      concurrent_fragments: concurrentFragments,
      playlist_items: playlistItemsValue(selectedPlaylistIndexes, analysis?.playlist_count),
      playlist_title: analysis?.is_playlist ? rawText(analysis, 'collection_title') || analysis.title || null : null,
      playlist_entries: selectedPlaylistEntries(analysis, selectedPlaylistIndexes),
      filename_template: taskFilenameTemplate(settings?.filename_template || filenameTemplatePresets[2].template, Boolean(analysis?.is_playlist)),
    };
    try {
      onTask(await api.createTask(request));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workspace-grid">
      <div className="panel acrylic">
        <div className="panel-header"><h2>{t('analyzeUrl')}</h2>{analysis && <span className="badge blue">{analysis.formats.length} {t('formatsCount')}</span>}</div>
        <div className="panel-body">
          <div className="urlbar">
            <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder={t('urlPlaceholder')} />
            <button onClick={() => navigator.clipboard?.readText().then(setUrl)}>{t('paste')}</button>
            <button className="primary" onClick={analyze} disabled={!url || busy}>{busy ? t('working') : t('analyze')}</button>
          </div>
          {error && <p className="error-line">{error}</p>}
          <AnalysisSummary analysis={analysis} t={t} />
          <AnalysisDetails analysis={analysis} mode={mode} selectedPlaylistIndexes={selectedPlaylistIndexes} selectedFormat={selectedFormat} onPlaylistSelected={setSelectedPlaylistIndexes} onFormatSelected={setSelectedFormat} t={t} />
        </div>
      </div>
      <aside className="panel acrylic">
        <div className="panel-header"><h2>{t('downloadOptions')}</h2><span className="badge">{t('queued')}</span></div>
        <div className="panel-body options-grid">
          <div className="segmented">
            {(['video', 'audio', 'subtitles'] as DownloadMode[]).map((item) => <button key={item} className={mode === item ? 'active' : ''} onClick={() => setMode(item)}>{modeLabel(item, t)}</button>)}
          </div>
          <label>{t('formatSelect')}<select value={selectedFormat || ''} onChange={(event) => setSelectedFormat(event.target.value || null)} disabled={mode === 'subtitles'}>
            <option value="">{mode === 'audio' ? 'bestaudio' : t('autoBestFormat')}</option>
            {modeFormats(analysis?.formats || [], mode).map((format) => <option key={format.format_id} value={format.format_id}>{formatLabel(format)}</option>)}
          </select></label>
          {mode === 'video' && <label>{t('videoOutputFormat')}<select value={videoOutputFormat} onChange={(event) => setVideoOutputFormat(event.target.value)}>
            {['mp4', 'webm', 'mkv'].map((format) => <option key={format} value={format}>{format}</option>)}
          </select></label>}
          {mode === 'audio' && <label>{t('audioOutputFormat')}<select value={audioFormat} onChange={(event) => setAudioFormat(event.target.value)}>
            {['mp3', 'm4a', 'opus', 'flac', 'wav'].map((format) => <option key={format} value={format}>{format}</option>)}
          </select></label>}
          {!!analysis?.subtitles.length && <div className="section-block compact-options"><div className="section-heading"><h3>{t('subtitleLanguages')}</h3><span className="badge blue">{selectedSubtitleLangs.length}</span></div><div className="check-grid">{analysis.subtitles.map((subtitle) => <label className="check" key={`${subtitle.language}-${subtitle.automatic ? 'auto' : 'manual'}`}><input type="checkbox" checked={selectedSubtitleLangs.includes(subtitle.language)} onChange={() => setSelectedSubtitleLangs((current) => toggleListItem(current, subtitle.language))} /> {subtitle.language}{subtitle.name ? ` - ${subtitle.name}` : ''}</label>)}</div></div>}
          <div className="check-grid">
            <label className="check"><input type="checkbox" checked={mergeSubtitles} onChange={(event) => setMergeSubtitles(event.target.checked)} /> {t('mergeSubtitles')}</label>
            <label className="check"><input type="checkbox" checked={saveThumbnail} onChange={(event) => setSaveThumbnail(event.target.checked)} /> {t('saveThumbnail')}</label>
            <label className="check"><input type="checkbox" checked={saveDescription} onChange={(event) => setSaveDescription(event.target.checked)} /> {t('saveDescription')}</label>
            <label className="check"><input type="checkbox" checked={embedChapters} onChange={(event) => setEmbedChapters(event.target.checked)} /> {t('embedChapters')}</label>
            <label className="check"><input type="checkbox" checked={audioNormalization} onChange={(event) => setAudioNormalization(event.target.checked)} disabled={mode !== 'audio'} /> {t('normalizeAudio')}</label>
          </div>
          <label>{t('proxyUrl')}<input value={proxyUrl} placeholder={t('proxyPlaceholder')} onChange={(event) => setProxyUrl(event.target.value)} /></label>
          <label>{t('concurrentFragments')}<input type="number" min="1" max="16" value={concurrentFragments} onChange={(event) => setConcurrentFragments(Math.max(1, Math.min(16, Number(event.target.value) || 1)))} /></label>
          <button className="primary" onClick={createTask} disabled={!url || busy || Boolean(analysis?.is_playlist && selectedPlaylistIndexes.length === 0)}>{t('createTask')}</button>
        </div>
      </aside>
    </div>
  );
}

function rawText(analysis: AnalyzeResponse, key: string): string | null {
  const value = analysis.raw?.[key];
  return typeof value === 'string' && value ? value : null;
}

function warningText(analysis: AnalyzeResponse, t: T): string | null {
  const code = rawText(analysis, 'warning_code') || rawText(analysis, 'warning');
  if (code === 'metadata_without_formats') return t('metadataWithoutFormats');
  return code;
}

function AnalysisSummary({ analysis, t }: { analysis: AnalyzeResponse | null; t: T }) {
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  useEffect(() => setThumbnailFailed(false), [analysis?.thumbnail_url]);
  if (!analysis) return <div className="empty-state">{t('analyzeEmpty')}</div>;
  const warning = warningText(analysis, t);
  const webpageUrl = rawText(analysis, 'webpage_url');
  const originalUrl = rawText(analysis, 'original_url');
  const extractor = rawText(analysis, 'extractor') || rawText(analysis, 'extractor_key');
  const thumbnailUrl = analysis.thumbnail_url && !thumbnailFailed ? analysis.thumbnail_url : '/static/assets/main.png';
  return (
    <div className="summary">
      <div className="preview"><img key={thumbnailUrl} src={thumbnailUrl} alt="Video thumbnail" referrerPolicy="no-referrer" onError={() => setThumbnailFailed(true)} /></div>
      <div className="stack">
        <h2>{analysis.title || t('untitled')}</h2>
        <span className="muted">{analysis.channel || t('unknownChannel')} {analysis.duration ? `- ${Math.round(analysis.duration / 60)} ${t('minutes')}` : ''}</span>
        <div className="badge-row">
          <span className={`badge ${warning ? 'amber' : 'green'}`}>{warning ? t('fallbackFormats') : t('formatsReady')}</span>
          <span className="badge blue">{t('subtitles')}: {analysis.subtitles.length}</span>
          {analysis.is_playlist && <span className="badge amber">{t('playlist')}: {analysis.playlist_count}</span>}
          {extractor && <span className="badge">{t('extractor')}: {extractor}</span>}
        </div>
        {warning && <p className="notice-line"><strong>{t('analyzeWarning')}:</strong> {warning}</p>}
        <div className="meta-grid">
          {webpageUrl && <a href={webpageUrl} target="_blank" rel="noreferrer"><span>{t('sourcePage')}</span><strong>{webpageUrl}</strong></a>}
          {originalUrl && originalUrl !== webpageUrl && <a href={originalUrl} target="_blank" rel="noreferrer"><span>{t('originalUrl')}</span><strong>{originalUrl}</strong></a>}
        </div>
      </div>
    </div>
  );
}

type AnalysisTab = 'playlist' | 'formats';

function AnalysisDetails({ analysis, mode, selectedPlaylistIndexes, selectedFormat, onPlaylistSelected, onFormatSelected, t }: {
  analysis: AnalyzeResponse | null;
  mode: DownloadMode;
  selectedPlaylistIndexes: number[];
  selectedFormat: string | null;
  onPlaylistSelected: (indexes: number[]) => void;
  onFormatSelected: (id: string) => void;
  t: T;
}) {
  const hasPlaylist = Boolean(analysis?.playlist_entries.length);
  const [tab, setTab] = useState<AnalysisTab>('formats');
  useEffect(() => {
    setTab(hasPlaylist ? 'playlist' : 'formats');
  }, [analysis?.url, hasPlaylist]);
  if (!analysis) return null;
  return <div className="section-block analysis-details">
    <div className="segmented compact-segmented">
      <button className={tab === 'playlist' ? 'active' : ''} disabled={!hasPlaylist} onClick={() => setTab('playlist')}>{t('analysisPlaylistTab')} {hasPlaylist ? `(${analysis.playlist_entries.length})` : ''}</button>
      <button className={tab === 'formats' ? 'active' : ''} onClick={() => setTab('formats')}>{t('analysisFormatsTab')} ({analysis.formats.length})</button>
    </div>
    {tab === 'playlist' && <PlaylistTable entries={analysis.playlist_entries} selected={selectedPlaylistIndexes} onSelected={onPlaylistSelected} t={t} />}
    {tab === 'formats' && <FormatTable formats={modeFormats(analysis.formats, mode)} selected={selectedFormat} onSelected={onFormatSelected} t={t} />}
  </div>;
}

function PlaylistTable({ entries, selected, onSelected, t }: { entries: PlaylistEntry[]; selected: number[]; onSelected: (indexes: number[]) => void; t: T }) {
  const [page, setPage] = useState(0);
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(entries.length / pageSize));
  const pageItems = paginationItems(page + 1, pageCount);
  useEffect(() => setPage(0), [entries]);
  if (!entries.length) return null;
  const pageEntries = entries.slice(page * pageSize, page * pageSize + pageSize);
  const selectedSet = new Set(selected);
  const allSelected = selected.length === entries.length;
  function toggle(index: number) {
    if (selectedSet.has(index)) onSelected(selected.filter((item) => item !== index));
    else onSelected([...selected, index].sort((a, b) => a - b));
  }
  return (
    <div className="section-block">
      <div className="section-heading">
        <h2>{t('playlistSelection')}</h2>
        <div className="toolbar">
          <span className="badge blue">{selected.length} {t('selectedItemsCount')}</span>
          <span className="badge">{formatPageInfo(t('pageInfo'), page + 1, pageCount, entries.length)}</span>
          <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page <= 0}>{t('previousPage')}</button>
          <div className="page-list compact-page-list" aria-label="Pagination">{pageItems.map((item, index) => item === 'ellipsis' ? <span className="page-ellipsis" key={`playlist-ellipsis-${index}`}>...</span> : <button className={item === page + 1 ? 'active' : ''} key={item} onClick={() => setPage(item - 1)} disabled={item === page + 1} aria-current={item === page + 1 ? 'page' : undefined}>{item}</button>)}</div>
          <button onClick={() => setPage(Math.min(pageCount - 1, page + 1))} disabled={page >= pageCount - 1}>{t('nextPage')}</button>
          <button onClick={() => onSelected(entries.map((entry) => entry.index))} disabled={allSelected}>{t('allItems')}</button>
          <button onClick={() => onSelected([])} disabled={!selected.length}>{t('clearItems')}</button>
        </div>
      </div>
      <div className="table-wrap playlist-wrap">
        <table>
          <thead><tr><th>{t('pick')}</th><th>{t('playlistIndex')}</th><th>{t('title')}</th><th>{t('channel')}</th><th>{t('duration')}</th></tr></thead>
          <tbody>{pageEntries.map((entry) => <tr key={entry.index} className={selectedSet.has(entry.index) ? 'selected' : ''} onClick={() => toggle(entry.index)}>
            <td><input type="checkbox" checked={selectedSet.has(entry.index)} onChange={() => toggle(entry.index)} onClick={(event) => event.stopPropagation()} /></td>
            <td>{entry.index}</td>
            <td><strong>{entry.title || entry.id || entry.url || '-'}</strong></td>
            <td>{entry.channel || '-'}</td>
            <td>{entry.duration ? `${Math.round(entry.duration / 60)} ${t('minutes')}` : '-'}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}

function FormatTable({ formats, selected, onSelected, t }: { formats: FormatInfo[]; selected: string | null; onSelected: (id: string) => void; t: T }) {
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const pageCount = Math.max(1, Math.ceil(formats.length / pageSize));
  useEffect(() => setPage(0), [formats]);
  if (!formats.length) return null;
  const pageFormats = formats.slice(page * pageSize, page * pageSize + pageSize);
  return (
    <div className="section-block">
      <div className="section-heading">
        <h2>{t('analysisFormatsTab')}</h2>
        <div className="toolbar">
          <span className="badge">{formatPageInfo(t('pageInfo'), page + 1, pageCount, formats.length)}</span>
          <button onClick={() => setPage(Math.max(0, page - 1))} disabled={page <= 0}>{t('previousPage')}</button>
          <button onClick={() => setPage(Math.min(pageCount - 1, page + 1))} disabled={page >= pageCount - 1}>{t('nextPage')}</button>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>{t('pick')}</th><th>{t('type')}</th><th>{t('resolution')}</th><th>{t('ext')}</th><th>{t('video')}</th><th>{t('audio')}</th><th>{t('fps')}</th><th>{t('size')}</th><th>{t('id')}</th></tr></thead>
          <tbody>{pageFormats.map((format) => <tr key={format.format_id} className={selected === format.format_id ? 'selected' : ''} onClick={() => onSelected(format.format_id)}>
            <td><input type="radio" checked={selected === format.format_id} onChange={() => onSelected(format.format_id)} /></td>
            <td>{format.type}</td><td>{format.resolution || '-'}</td><td>{format.ext || '-'}</td><td>{format.video_codec || '-'}</td><td>{format.audio_codec || '-'}</td><td>{format.fps || '-'}</td><td>{formatBytes(format.filesize)}</td><td>{format.format_id}</td>
          </tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}

function taskPlaylistEntries(task: TaskResponse): PlaylistEntry[] {
  const entries = task.options.playlist_entries;
  return Array.isArray(entries) ? entries.filter((entry): entry is PlaylistEntry => typeof entry === 'object' && entry !== null && typeof (entry as PlaylistEntry).index === 'number') : [];
}

type PlaylistItemState = 'pending' | 'downloading' | 'completed' | 'failed';

function playlistItemState(task: TaskResponse, entry: PlaylistEntry): PlaylistItemState {
  const failed = new Set(task.progress.playlist_failed_indexes || []);
  if (failed.has(entry.index)) return 'failed';
  const currentIndex = task.progress.playlist_current_index;
  const lastIndex = task.progress.playlist_last_index || currentIndex;
  if (task.status === 'completed') return 'completed';
  if (task.status === 'failed' || task.status === 'cancelled' || task.status === 'interrupted') {
    return lastIndex && entry.index <= lastIndex ? 'completed' : 'pending';
  }
  if (currentIndex === entry.index) return 'downloading';
  if (currentIndex && entry.index < currentIndex) return 'completed';
  return 'pending';
}

function playlistItemStateLabel(state: PlaylistItemState, t: T): string {
  const labels: Record<PlaylistItemState, TKey> = {
    pending: 'itemPending',
    downloading: 'itemDownloading',
    completed: 'itemCompleted',
    failed: 'itemFailed',
  };
  return t(labels[state]);
}

function playlistItemStateTone(state: PlaylistItemState): string {
  const tones: Record<PlaylistItemState, string> = {
    pending: '',
    downloading: 'blue',
    completed: 'green',
    failed: 'red',
  };
  return tones[state];
}

function TaskPlaylist({ task, api, t, onChanged }: { task: TaskResponse; api: ReturnType<typeof createApiClient>; t: T; onChanged: () => void }) {
  const entries = taskPlaylistEntries(task);
  const [expanded, setExpanded] = useState(() => task.status === 'running' || task.status === 'queued');
  useEffect(() => {
    if (task.status === 'running') setExpanded(true);
  }, [task.status]);
  if (!entries.length) return null;
  async function retryItem(entry: PlaylistEntry) {
    await api.retryPlaylistItem(task.id, entry.index);
    onChanged();
  }
  const counts = entries.reduce<Record<PlaylistItemState, number>>((result, entry) => {
    result[playlistItemState(task, entry)] += 1;
    return result;
  }, { pending: 0, downloading: 0, completed: 0, failed: 0 });
  return <div className="task-playlist"><div className="section-heading"><h3>{t('taskPlaylist')}</h3><div className="toolbar"><span className="badge blue">{entries.length}</span><span className="badge green">{t('itemCompleted')}: {counts.completed}</span><span className="badge red">{t('itemFailed')}: {counts.failed}</span><button onClick={() => setExpanded((value) => !value)}>{expanded ? t('collapse') : t('expand')}</button></div></div>
    {expanded && <div className="task-playlist-list">{entries.map((entry) => {
      const state = playlistItemState(task, entry);
      const failure = task.progress.playlist_failures?.[String(entry.index)];
      return <div key={entry.index} className={`task-playlist-item ${state === 'downloading' ? 'current' : ''}`} title={failure || undefined}>
        <span className="badge">{entry.index}</span>
        <strong>{entry.title || entry.id || entry.url || '-'}</strong>
        <span className={`badge ${playlistItemStateTone(state)}`}>{playlistItemStateLabel(state, t)}</span>
        {state === 'failed' && <button onClick={() => void retryItem(entry)}>{t('retryItem')}</button>}
      </div>;
    })}</div>}
  </div>;
}

function Tasks({ tasks, api, t, onChanged, onCancel }: { tasks: TaskResponse[]; api: ReturnType<typeof createApiClient>; t: T; onChanged: () => void; onCancel: (id: string) => Promise<void> }) {
  async function deleteTask(id: string) {
    await api.deleteTask(id);
    onChanged();
  }
  async function clearTasks() {
    if (!window.confirm(t('confirmClearTasks'))) return;
    await api.clearTasks();
    onChanged();
  }
  if (!tasks.length) return <div className="empty-state">{t('noTasks')}</div>;
  return <div className="stack"><div className="toolbar"><button onClick={() => void clearTasks()}>{t('clearRecords')}</button></div><div className="list">{tasks.map((task) => <div className="row" key={task.id}>
    <div className="row-top"><div className="stack"><strong>{String(task.options.url || task.url)}</strong><span className="muted">{task.progress.current_filename || task.output_path || task.id}</span></div><span className={`badge ${statusTone(task.status)}`}>{statusLabel(task.status, t)}</span></div>
    <TaskPlaylist task={task} api={api} t={t} onChanged={onChanged} />
    <div className="progress"><span style={{ width: `${Math.max(0, Math.min(100, task.progress.percent || 0))}%` }} /></div>
    <div className="row-top"><span className="muted">{task.progress.status_text || `${task.progress.speed || '-'} - ETA ${task.progress.eta || '-'}`}</span><div className="toolbar">{['queued', 'running'].includes(task.status) && <button className="danger" onClick={() => void onCancel(task.id)}>{t('cancel')}</button>}<button onClick={() => void deleteTask(task.id)}>{t('deleteRecord')}</button></div></div>
    {task.error && <pre className="log-box">{task.error}</pre>}
  </div>)}</div></div>;
}

function History({ entries, api, t, onChanged, onOpenFiles }: { entries: HistoryEntry[]; api: ReturnType<typeof createApiClient>; t: T; onChanged: () => void; onOpenFiles: () => void }) {
  async function deleteHistory(id: string) {
    await api.deleteHistory(id);
    onChanged();
  }
  async function clearHistory() {
    if (!window.confirm(t('confirmClearHistory'))) return;
    await api.clearHistory();
    onChanged();
  }
  if (!entries.length) return <div className="empty-state">{t('noHistory')}</div>;
  return <div className="stack"><div className="toolbar"><button onClick={() => void clearHistory()}>{t('clearRecords')}</button></div><div className="list">{entries.map((entry) => <div className="row" key={entry.id}>
    <div className="row-top"><div className="stack"><strong>{entry.title || entry.url || entry.id}</strong><span className="muted">{entry.downloaded_at} - {formatBytes(entry.file_size)} - {mediaLabel(entry.media_type, t)}</span></div><span className={`badge ${statusTone(entry.status)}`}>{statusLabel(entry.status, t)}</span></div>
    <div className="toolbar"><button onClick={onOpenFiles}>{t('openFiles')}</button><button disabled={!entry.url}>{t('redownload')}</button><button onClick={() => entry.output_path && navigator.clipboard?.writeText(entry.output_path)}>{t('copyPath')}</button><button onClick={() => void deleteHistory(entry.id)}>{t('deleteRecord')}</button></div>
  </div>)}</div></div>;
}

function Files({ library, token, api, t, onLoaded, onPlay }: { library: FileListResponse | null; token: string; api: ReturnType<typeof createApiClient>; t: T; onLoaded: (library: FileListResponse) => void; onPlay: (file: FileEntry, queue: FileEntry[], folder: string) => void }) {
  const [query, setQuery] = useState('');
  const [folder, setFolder] = useState('');
  const [mediaPage, setMediaPage] = useState(1);
  const files = library?.files || [];
  const mediaFiles = files.filter((file) => file.playable && (file.media_type === 'video' || file.media_type === 'audio') && directParent(file.relative_path) === folder);
  const mediaPageSize = 30;
  const mediaPages = Math.max(1, Math.ceil(mediaFiles.length / mediaPageSize));
  const normalizedMediaPage = Math.min(mediaPages, Math.max(1, mediaPage));
  const visibleMediaFiles = mediaFiles.slice((normalizedMediaPage - 1) * mediaPageSize, normalizedMediaPage * mediaPageSize);
  const mediaPageItems = paginationItems(normalizedMediaPage, mediaPages);
  const folderItems = library?.folders || [];
  const limit = library?.limit || 200;
  const authSuffix = token ? `?token=${encodeURIComponent(token)}` : '';
  const fileUrl = (url?: string | null) => url ? `${url}${authSuffix}` : '#';
  const folderUrl = folder ? `${api.downloadFolderUrl(folder)}${token ? `&token=${encodeURIComponent(token)}` : ''}` : '#';
  const manifestUrl = folder ? `${api.folderManifestUrl(folder)}${token ? `&token=${encodeURIComponent(token)}` : ''}` : '#';
  async function load(nextOffset = 0, nextQuery = query, nextFolder = folder) {
    onLoaded(await api.files(nextQuery, nextFolder, nextOffset, limit));
  }
  async function changeFolder(value: string) {
    setFolder(value);
    setMediaPage(1);
    await load(0, query, value);
  }
  useEffect(() => {
    if (!library) void load(0);
  }, [library]);
  return <div className="file-browser-grid">
    <aside className="panel acrylic file-tree-panel">
      <div className="panel-header"><h2>{t('folderTree')}</h2><span className="badge blue">{folderItems.length}</span></div>
      <div className="file-tree-list">
        <button className={`tree-item ${folder === '' ? 'active' : ''}`} onClick={() => void changeFolder('')}><span className="tree-indent" style={{ width: 0 }} />{t('allFolders')}</button>
        {folderItems.map((item) => <button className={`tree-item ${folder === item ? 'active' : ''}`} key={item} onClick={() => void changeFolder(item)}><span className="tree-indent" style={{ width: `${Math.max(0, item.split('/').length - 1) * 14}px` }} />{item.split('/').pop() || item}</button>)}
      </div>
    </aside>
    <section className="panel acrylic file-media-panel"><div className="panel-header"><div className="stack"><h2>{t('mediaInFolder')}</h2><span className="muted">{folder || t('allFolders')} - {t('directMediaOnly')}</span></div><div className="toolbar file-toolbar-inline">
      <input value={query} placeholder={t('searchFiles')} onChange={(event) => setQuery(event.target.value)} />
      <button onClick={() => { setMediaPage(1); void load(0); }}>{t('search')}</button>
      <a className={`button-link ${folder ? '' : 'disabled'}`} href={manifestUrl} aria-disabled={!folder} onClick={(event) => { if (!folder) event.preventDefault(); }}>{t('downloadManifest')}</a>
      <a className={`button-link ${folder ? '' : 'disabled'}`} href={folderUrl} aria-disabled={!folder} onClick={(event) => { if (!folder) event.preventDefault(); }}>{t('downloadFolder')}</a>
    </div></div><div className="panel-body media-table-body">
      {!mediaFiles.length && <div className="empty-state">{t('noFiles')}</div>}
      {!!mediaFiles.length && <div className="media-table-wrap"><table className="media-table"><thead><tr><th>{t('title')}</th><th>{t('type')}</th><th>{t('size')}</th><th></th></tr></thead><tbody>{visibleMediaFiles.map((file) => <tr key={file.id}><td><strong>{file.name}</strong></td><td><span className="badge green">{mediaLabel(file.media_type, t)}</span></td><td>{formatBytes(file.size)}</td><td><div className="toolbar compact-actions"><button onClick={() => onPlay(file, mediaFiles, folder)}>{t('play')}</button><a className="button-link" href={fileUrl(file.download_url)}>{t('download')}</a><button onClick={() => navigator.clipboard?.writeText(fileUrl(file.download_url))}>{t('copyLink')}</button></div></td></tr>)}</tbody></table></div>}
      <div className="pagination-row"><button onClick={() => setMediaPage(Math.max(1, normalizedMediaPage - 1))} disabled={normalizedMediaPage <= 1}>{t('previousPage')}</button><span className="muted">{formatPageInfo(t('pageInfo'), normalizedMediaPage, mediaPages, mediaFiles.length)}</span><div className="page-list" aria-label="Pagination">{mediaPageItems.map((item, index) => item === 'ellipsis' ? <span className="page-ellipsis" key={`ellipsis-${index}`}>...</span> : <button className={item === normalizedMediaPage ? 'active' : ''} key={item} onClick={() => setMediaPage(item)} disabled={item === normalizedMediaPage} aria-current={item === normalizedMediaPage ? 'page' : undefined}>{item}</button>)}</div><button onClick={() => setMediaPage(Math.min(mediaPages, normalizedMediaPage + 1))} disabled={normalizedMediaPage >= mediaPages}>{t('nextPage')}</button></div>
    </div></section>
  </div>;
}

function PlayerPage({ current, queue, folder, token, api, t, onSelect, onQueue, onFolder }: { current: FileEntry | null; queue: FileEntry[]; folder: string; token: string; api: ReturnType<typeof createApiClient>; t: T; onSelect: (file: FileEntry | null) => void; onQueue: (files: FileEntry[]) => void; onFolder: (folder: string) => void }) {
  const [folders, setFolders] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const playerRef = useRef<HTMLDivElement | null>(null);
  const artRef = useRef<Artplayer | null>(null);
  const authSuffix = token ? `?token=${encodeURIComponent(token)}` : '';
  const fileUrl = (url?: string | null) => url ? `${url}${authSuffix}` : '#';
  const active = current || queue[0] || null;

  async function loadFolder(nextFolder: string) {
    setLoading(true);
    onFolder(nextFolder);
    try {
      const result = await api.files('', nextFolder, 0, 200);
      setFolders(result.folders);
      const mediaFiles = result.files.filter((file) => file.playable && (file.media_type === 'video' || file.media_type === 'audio'));
      onQueue(mediaFiles);
      onSelect(mediaFiles[0] || null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void api.files('', '', 0, 1).then((result) => setFolders(result.folders));
  }, [api]);

  useEffect(() => {
    if (!queue.length) void loadFolder(folder);
  }, []);

  useEffect(() => {
    if (!playerRef.current || !active) return;
    artRef.current?.destroy(false);
    artRef.current = new Artplayer({
      container: playerRef.current,
      url: fileUrl(active.stream_url),
      type: active.media_type === 'audio' ? 'audio' : 'mp4',
      autoplay: true,
      setting: true,
      playbackRate: false,
      controls: [
        {
          position: 'right',
          html: '倍速',
          selector: [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2].map((rate) => ({ html: `${rate}x`, value: rate, default: rate === 1 })),
          onSelect: (item: { value?: string | number }) => {
            const rate = Number(item.value || 1);
            if (artRef.current) artRef.current.playbackRate = rate;
            return `${rate}x`;
          },
        },
      ],
      aspectRatio: true,
      fullscreen: true,
      fullscreenWeb: true,
      hotkey: true,
      pip: active.media_type === 'video',
      mutex: true,
      moreVideoAttr: { preload: 'metadata' },
    });
    return () => {
      artRef.current?.destroy(false);
      artRef.current = null;
    };
  }, [active?.id, token]);

  return <div className="watch-layout">
    <section className="watch-main">
      <div className="watch-player-shell">
        {!active && <div className="empty-state">{t('selectPlayable')}</div>}
        {active && <div className={`art-player-host ${active.media_type === 'audio' ? 'audio-mode' : ''}`} ref={playerRef} />}
      </div>
      {active && <div className="watch-meta"><h2>{active.name}</h2><p className="muted">{playlistMeta(active, t)}</p><div className="toolbar"><a className="button-link primary-link" href={fileUrl(active.download_url)}>{t('download')}</a><button onClick={() => navigator.clipboard?.writeText(fileUrl(active.download_url))}>{t('copyLink')}</button></div></div>}
    </section>
    <aside className="watch-list panel acrylic"><div className="panel-header"><h2>{t('playQueue')}</h2><span className="badge blue">{queue.length}</span></div><div className="watch-folder-bar"><label>{t('playerFolder')}<select value={folder} onChange={(event) => void loadFolder(event.target.value)}><option value="">{t('allFolders')}</option>{folders.map((item) => <option key={item} value={item}>{item}</option>)}</select></label></div><div className="watch-list-body">{loading && <div className="empty-state">{t('working')}</div>}{!loading && !queue.length && <div className="empty-state">{t('selectPlayable')}</div>}{!loading && queue.map((file) => <button key={file.id} className={`watch-list-item ${active?.id === file.id ? 'active' : ''}`} onClick={() => onSelect(file)}><span className="watch-thumb">{file.media_type === 'audio' ? 'A' : 'V'}</span><span className="stack"><strong>{file.name}</strong><span className="muted">{playlistMeta(file, t)}</span></span></button>)}</div></aside>
  </div>;
}

function paginationItems(currentPage: number, totalPages: number): Array<number | 'ellipsis'> {
  if (totalPages <= 9) return Array.from({ length: totalPages }, (_, index) => index + 1);

  const pages = new Set<number>([1, totalPages]);
  for (let item = currentPage - 2; item <= currentPage + 2; item += 1) {
    if (item > 1 && item < totalPages) pages.add(item);
  }
  if (currentPage <= 4) {
    [2, 3, 4, 5].forEach((item) => pages.add(item));
  }
  if (currentPage >= totalPages - 3) {
    [totalPages - 4, totalPages - 3, totalPages - 2, totalPages - 1].forEach((item) => pages.add(item));
  }

  const sortedPages = [...pages].filter((item) => item >= 1 && item <= totalPages).sort((a, b) => a - b);
  return sortedPages.flatMap((item, index) => {
    const previous = sortedPages[index - 1];
    return previous && item - previous > 1 ? ['ellipsis' as const, item] : [item];
  });
}

function readonlyValue(value: string): React.ReactNode {
  return <div className="readonly-value">{value || '-'}</div>;
}

function cookieProfileLabel(profile: string, t: T): string {
  const labels: Record<string, TKey> = {
    default: 'cookieProfileDefault',
    bilibili: 'cookieProfileBilibili',
    youtube: 'cookieProfileYoutube',
  };
  return labels[profile] ? t(labels[profile]) : profile;
}

function Settings({ api, settings, token, t, onToken, onSaved }: { api: ReturnType<typeof createApiClient>; settings: SettingsResponse | null; token: string; t: T; onToken: (value: string) => void; onSaved: () => void }) {
  const [cookieContent, setCookieContent] = useState('');
  const [cookieProfile, setCookieProfile] = useState('default');
  const [filenameTemplate, setFilenameTemplate] = useState(filenameTemplatePresets[2].template);
  const [defaultVideoResolution, setDefaultVideoResolution] = useState('best');
  const [filenameTemplateStatus, setFilenameTemplateStatus] = useState<string | null>(null);
  const [cookieStatus, setCookieStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (settings?.filename_template) setFilenameTemplate(settings.filename_template);
    if (settings?.default_video_resolution) setDefaultVideoResolution(settings.default_video_resolution);
  }, [settings?.filename_template, settings?.default_video_resolution]);

  async function saveCookies(content: string) {
    setBusy(true);
    setCookieStatus(null);
    try {
      const result = await api.saveCookies(content, cookieProfile);
      setCookieContent('');
      setCookieStatus(`${cookieProfileLabel(result.profile, t)}: ${result.cookies_configured ? t('cookiesSaved') : t('cookiesCleared')}`);
      onSaved();
    } catch (err) {
      setCookieStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function loadCookieFile(file: File | undefined) {
    if (!file) return;
    setCookieContent(await file.text());
  }

  async function saveFilenameTemplateSetting() {
    setBusy(true);
    setFilenameTemplateStatus(null);
    try {
      await api.saveFilenameTemplate(filenameTemplate, defaultVideoResolution);
      setFilenameTemplateStatus(t('filenameTemplateSaved'));
      onSaved();
    } catch (err) {
      setFilenameTemplateStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return <div className="panel acrylic"><div className="panel-body settings-grid">
    <label>{t('downloadDir')}{readonlyValue(settings?.download_dir || '')}</label>
    <label>{t('configDir')}{readonlyValue(settings?.config_dir || '')}</label>
    <label>{t('filenameTemplatePreset')}<select value={filenameTemplatePresets.some((preset) => preset.template === filenameTemplate) ? filenameTemplate : 'custom'} onChange={(event) => { const preset = filenameTemplatePresets.find((item) => item.template === event.target.value); if (preset) setFilenameTemplate(preset.template); }}>
      {filenameTemplatePresets.map((preset) => <option key={preset.id} value={preset.template}>{preset.template} - {t(preset.descKey)}</option>)}
      <option value="custom">{t('filenameTemplateCustom')} - {t('filenameTemplateDescCustom')}</option>
    </select></label>
    <label className="wide-field">{t('filenameTemplate')}<input value={filenameTemplate} onChange={(event) => setFilenameTemplate(event.target.value)} /></label>
    <label>{t('defaultVideoResolution')}<select value={defaultVideoResolution} onChange={(event) => setDefaultVideoResolution(event.target.value)}>{videoResolutionOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
    <div className="wide-field toolbar"><button className="primary" onClick={() => void saveFilenameTemplateSetting()} disabled={busy || !filenameTemplate.trim()}>{t('saveSettings')}</button>{filenameTemplateStatus && <span className="muted">{filenameTemplateStatus}</span>}</div>
    <label>{t('queueConcurrency')}{readonlyValue(String(settings?.queue_concurrency || 2))}</label>
    <label>{t('authConfigured')}{readonlyValue(settings?.auth_configured ? t('yes') : t('no'))}</label>
    <label>{t('optionalAuthToken')}<input value={token} placeholder={t('notConfigured')} onChange={(event) => onToken(event.target.value)} /></label>
    <label>{t('cookiesConfigured')}{readonlyValue(['default', 'bilibili', 'youtube'].map((profile) => `${cookieProfileLabel(profile, t)}: ${settings?.cookie_profiles?.[profile] ? t('configured') : t('notConfigured')}`).join(' / '))}</label>
    <label>{t('cookieProfile')}<select value={cookieProfile} onChange={(event) => setCookieProfile(event.target.value)}>
      {['default', 'bilibili', 'youtube'].map((profile) => <option key={profile} value={profile}>{cookieProfileLabel(profile, t)}</option>)}
    </select></label>
    <label className="wide-field">{t('cookiePaste')}<textarea className="cookie-textarea" value={cookieContent} placeholder={t('cookiePastePlaceholder')} onChange={(event) => setCookieContent(event.target.value)} /></label>
    <div className="wide-field toolbar">
      <label className="file-button"><input type="file" accept=".txt,.cookies" onChange={(event) => void loadCookieFile(event.target.files?.[0])} />{t('uploadCookieFile')}</label>
      <button className="primary" onClick={() => void saveCookies(cookieContent)} disabled={busy || !cookieContent.trim()}>{busy ? t('working') : t('saveCookies')}</button>
      <button onClick={() => void saveCookies('')} disabled={busy || !settings?.cookie_profiles?.[cookieProfile]}>{t('clearCookies')}</button>
      {cookieStatus && <span className="muted">{cookieStatus}</span>}
    </div>
  </div></div>;
}

function System({ api, health, settings, t, onChanged }: { api: ReturnType<typeof createApiClient>; health: HealthResponse | null; settings: SettingsResponse | null; t: T; onChanged: () => void }) {
  const [updating, setUpdating] = useState(false);
  const [updateStatus, setUpdateStatus] = useState<string | null>(null);
  const details = [
    ['download_dir', settings?.download_dir || '-'],
    ['config_dir', settings?.config_dir || '-'],
    ['queue_concurrency', String(settings?.queue_concurrency || '-')],
    ['auth_configured', String(settings?.auth_configured || false)],
    ['yt_dlp', health?.yt_dlp || '-'],
    ['ffmpeg', health?.ffmpeg || '-'],
  ];
  async function updateDependencies() {
    setUpdating(true);
    setUpdateStatus(null);
    try {
      const result = await api.updateDependencies();
      setUpdateStatus(`${t('dependenciesUpdated')}: yt-dlp ${result.yt_dlp_version || result.yt_dlp}, ffmpeg ${result.ffmpeg_version || result.ffmpeg}`);
      onChanged();
    } catch (err) {
      setUpdateStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setUpdating(false);
    }
  }
  return <div className="stack">
    <div className="toolbar"><button className="primary" onClick={() => void updateDependencies()} disabled={updating}>{updating ? t('working') : t('updateDependencies')}</button>{updateStatus && <span className="muted">{updateStatus}</span>}</div>
    <div className="system-grid">
      <div className="row"><span className={`badge ${health?.healthy ? 'green' : 'amber'}`}>{health?.healthy ? t('healthy') : t('needsAttention')}</span><h2>{t('api')}</h2><p className="muted">{t('fastapiServer')}</p></div>
      <div className="row"><span className={`badge ${health?.yt_dlp !== 'not found' ? 'green' : 'red'}`}>{health?.yt_dlp || t('unknown')}</span><h2>yt-dlp</h2><p className="muted">{t('requiredAnalyze')}</p></div>
      <div className="row"><span className={`badge ${health?.ffmpeg !== 'not found' ? 'green' : 'red'}`}>{health?.ffmpeg !== 'not found' ? t('configured') : t('needsAttention')}</span><h2>ffmpeg</h2><p className="muted">{t('requiredMuxing')}</p></div>
    </div>
    <div className="panel acrylic"><div className="panel-header"><h2>{t('serverDetails')}</h2><span className="badge">{t('stdout')}</span></div><div className="panel-body detail-list">{details.map(([label, value]) => <div className="detail-row" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div></div>
  </div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
