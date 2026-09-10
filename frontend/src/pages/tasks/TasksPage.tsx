import { AlertTriangle, Ban, Check, CheckCircle2, ChevronDown, Clock3, Copy, Download, ExternalLink, ListFilter, ListVideo, Play, Radar, RefreshCw, Search, Trash2, XCircle } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { TaskResponse, TaskStatus } from '../../api/types';
import type { T, TKey } from '../../i18n';
import { formatBytes, statusLabel, statusTone } from '../../shared/format';
import { TaskPlaylist } from './TaskPlaylist';

interface TasksPageProps {
  tasks: TaskResponse[];
  api: ApiClient;
  t: T;
  onChanged: () => void | Promise<void>;
  onCancel: (id: string) => Promise<void>;
}

type TaskFilter = 'all' | 'active' | 'failed' | 'completed';
const activeStatuses = new Set<TaskStatus>(['queued', 'running']);
const failedStatuses = new Set<TaskStatus>(['failed', 'cancelled', 'interrupted']);

function taskOption(task: TaskResponse, key: string): string | null {
  const value = task.options[key];
  return typeof value === 'string' && value.trim() ? value : null;
}

function taskTitle(task: TaskResponse): string {
  const playlistTitle = taskOption(task, 'playlist_title');
  if (playlistTitle) return playlistTitle;
  if (task.progress.current_filename) return task.progress.current_filename.split(/[\\/]/).pop() || task.progress.current_filename;
  if (task.output_path) return task.output_path.split(/[\\/]/).pop() || task.output_path;
  try {
    const url = new URL(task.url);
    return url.pathname.split('/').filter(Boolean).pop() || url.hostname;
  } catch {
    return task.url;
  }
}

function taskSource(task: TaskResponse): string {
  try {
    return new URL(task.url).hostname.replace(/^www\./, '');
  } catch {
    return task.url;
  }
}

function taskModeLabel(task: TaskResponse, t: T): string {
  const labels: Record<string, TKey> = { video: 'modeVideo', audio: 'modeAudio', subtitles: 'modeSubtitles' };
  return labels[task.mode] ? t(labels[task.mode]) : task.mode;
}

function playlistCounts(task: TaskResponse): { completed: number; failed: number; total: number } | null {
  const entries = task.options.playlist_entries;
  if (!Array.isArray(entries) || !entries.length) return null;
  const total = task.progress.playlist_total || entries.length;
  const failed = new Set(task.progress.playlist_failed_indexes || []).size;
  const recordedCompleted = task.progress.playlist_completed_indexes;
  let completed = new Set(recordedCompleted || []).size;
  if (task.status === 'completed') completed = Math.max(0, total - failed);
  else if (!recordedCompleted && task.progress.playlist_current_index) completed = Math.max(0, task.progress.playlist_current_index - 1 - failed);
  return { completed, failed, total };
}

function percentFor(task: TaskResponse, counts: ReturnType<typeof playlistCounts>): number {
  if (task.status === 'completed') return 100;
  if (counts?.total) return Math.max(0, Math.min(100, ((counts.completed + counts.failed) / counts.total) * 100));
  return Math.max(0, Math.min(100, task.progress.percent || 0));
}

function taskMatchesFilter(task: TaskResponse, filter: TaskFilter): boolean {
  if (filter === 'active') return activeStatuses.has(task.status);
  if (filter === 'failed') return failedStatuses.has(task.status);
  if (filter === 'completed') return task.status === 'completed';
  return true;
}

function taskTimestamp(task: TaskResponse): string {
  const detectedAt = taskOption(task, 'monitor_detected_at');
  return detectedAt || task.finished_at || task.started_at || task.created_at;
}

function taskCollectionKey(task: TaskResponse): string | null {
  const title = taskOption(task, 'playlist_title');
  return title && Array.isArray(task.options.playlist_entries) && task.options.playlist_entries.length ? `${task.url}\n${title}` : null;
}

function monitorTaskContext(task: TaskResponse, t: T, inferredBatch = false): { label: string; preview: string } | null {
  const origin = task.options.task_origin;
  if (origin !== 'monitor_initial' && origin !== 'monitor_update' && !inferredBatch) return null;
  const entries = Array.isArray(task.options.playlist_entries) ? task.options.playlist_entries as Array<Record<string, unknown>> : [];
  const configuredCount = task.options.monitor_new_item_count;
  const count = typeof configuredCount === 'number' ? configuredCount : entries.length;
  const titles = entries.map((entry) => typeof entry.title === 'string' ? entry.title : null).filter((title): title is string => Boolean(title));
  const visibleTitles = titles.slice(0, 2).join(' · ');
  const remaining = Math.max(0, titles.length - 2);
  return {
    label: `${t(origin === 'monitor_initial' ? 'monitorInitialBatch' : origin === 'monitor_update' ? 'monitorUpdateBatch' : 'collectionDownloadBatch')} · ${count} ${t('taskItems')}`,
    preview: `${visibleTitles}${remaining ? ` +${remaining}` : ''}`,
  };
}

function taskErrorSummary(error: string): string {
  const lines = error.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  return lines.find((line) => line.includes('ERROR:')) || lines.at(-1) || error;
}

function statusIcon(status: TaskStatus) {
  if (status === 'running') return Download;
  if (status === 'queued') return Clock3;
  if (status === 'completed') return CheckCircle2;
  return XCircle;
}

interface TaskDetailProps {
  task: TaskResponse;
  api: ApiClient;
  t: T;
  onChanged: () => void | Promise<void>;
  onCancel: (id: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onResume: (id: string) => Promise<void>;
  onRestart: (id: string) => Promise<void>;
}

function TaskDetail({ task, api, t, onChanged, onCancel, onDelete, onResume, onRestart }: TaskDetailProps) {
  const counts = playlistCounts(task);
  const percent = percentFor(task, counts);
  const active = activeStatuses.has(task.status);
  const recoverable = failedStatuses.has(task.status);
  const monitorContext = monitorTaskContext(task, t);
  const [copied, setCopied] = useState(false);
  const [busyAction, setBusyAction] = useState<'resume' | 'restart' | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    setCopied(false);
    setActionError(null);
    setBusyAction(null);
  }, [task.id]);

  async function runRecovery(action: 'resume' | 'restart') {
    setBusyAction(action);
    setActionError(null);
    try {
      if (action === 'resume') await onResume(task.id);
      else await onRestart(task.id);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyAction(null);
    }
  }

  async function copyTaskUrl() {
    if (navigator.clipboard) await navigator.clipboard.writeText(task.url);
    else {
      const input = document.createElement('textarea');
      input.value = task.url;
      input.style.position = 'fixed';
      input.style.opacity = '0';
      document.body.appendChild(input);
      input.select();
      document.execCommand('copy');
      input.remove();
    }
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }
  return <div className={`task-detail task-${task.status}`}>
    <header className="task-detail-header">
      <div className="task-detail-title"><span className={`task-status-icon ${statusTone(task.status)}`}>{(() => { const Icon = statusIcon(task.status); return <Icon aria-hidden="true" />; })()}</span><div><div className="task-title-row"><h2 title={taskTitle(task)}>{taskTitle(task)}</h2><span className={`badge ${statusTone(task.status)}`}>{statusLabel(task.status, t)}</span></div><p>{monitorContext ? `${monitorContext.label}${monitorContext.preview ? ` · ${monitorContext.preview}` : ''}` : task.progress.status_text || statusLabel(task.status, t)}</p></div></div>
      <div className="task-actions">{recoverable && <><button className="primary" onClick={() => void runRecovery('resume')} disabled={busyAction !== null}><Play aria-hidden="true" />{busyAction === 'resume' ? t('working') : t('resumeTask')}</button><button onClick={() => void runRecovery('restart')} disabled={busyAction !== null}><RefreshCw aria-hidden="true" />{busyAction === 'restart' ? t('working') : t('restartTask')}</button></>}{active && <button className="danger" onClick={() => void onCancel(task.id)}><Ban aria-hidden="true" />{t('cancel')}</button>}<button onClick={() => void onDelete(task.id)}><Trash2 aria-hidden="true" />{t('deleteRecord')}</button></div>
    </header>

    <div className="task-detail-progress"><div><strong>{Math.round(percent)}%</strong><span>{counts ? `${counts.completed} / ${counts.total} ${t('taskItems')}` : formatBytes(task.progress.downloaded_bytes)}</span></div><div className="task-progress-track" role="progressbar" aria-valuenow={Math.round(percent)} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${percent}%` }} /></div></div>

    <dl className="task-detail-facts">
      <div><dt>{t('downloadSpeed')}</dt><dd>{task.status === 'running' ? task.progress.speed || '-' : '-'}</dd></div>
      <div><dt>{t('eta')}</dt><dd>{task.status === 'running' ? task.progress.eta || '-' : '-'}</dd></div>
      <div><dt>{t('taskSource')}</dt><dd>{taskSource(task)}</dd></div>
      <div><dt>{t('type')}</dt><dd>{taskModeLabel(task, t)}</dd></div>
      <div><dt>{t('createdAt')}</dt><dd>{new Date(task.created_at).toLocaleString()}</dd></div>
      <div><dt>{t('updatedAt')}</dt><dd>{new Date(task.updated_at).toLocaleString()}</dd></div>
    </dl>

    <div className="task-detail-link">
      <div><span>{t('taskUrl')}</span><a href={task.url} target="_blank" rel="noreferrer" title={task.url}>{task.url}</a></div>
      <div><button onClick={() => void copyTaskUrl()} title={t('copyLink')} aria-label={t('copyLink')}>{copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}</button><a className="icon-button" href={task.url} target="_blank" rel="noreferrer" title={t('openSourceLink')} aria-label={t('openSourceLink')}><ExternalLink aria-hidden="true" /></a></div>
    </div>
    {task.progress.current_filename && <div className="task-detail-file"><span>{t('currentFile')}</span><strong>{task.progress.current_filename}</strong></div>}
    <TaskPlaylist task={task} api={api} t={t} onChanged={onChanged} />
    {actionError && <div className="task-action-error">{actionError}</div>}
    {task.error && <details className="task-error"><summary title={t('expand')}><span><AlertTriangle aria-hidden="true" /><strong>{t('taskError')}</strong></span><small>{taskErrorSummary(task.error)}</small><ChevronDown aria-hidden="true" /></summary><pre>{task.error}</pre></details>}
    <div className="task-detail-id"><span>{t('taskId')}</span><code>{task.id}</code></div>
  </div>;
}

export function TasksPage({ tasks, api, t, onChanged, onCancel }: TasksPageProps) {
  const [filter, setFilter] = useState<TaskFilter>('all');
  const [query, setQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  async function deleteTask(id: string) {
    await api.deleteTask(id);
    onChanged();
  }
  async function resumeTask(id: string) {
    await api.resumeTask(id);
    await onChanged();
  }
  async function restartTask(id: string) {
    const restarted = await api.restartTask(id);
    await onChanged();
    setSelectedId(restarted.id);
  }
  async function clearTasks() {
    if (!window.confirm(t('confirmClearTasks'))) return;
    await api.clearTasks();
    onChanged();
  }

  const repeatedCollectionKeys = useMemo(() => {
    const occurrences = new Map<string, number>();
    tasks.forEach((task) => {
      const key = taskCollectionKey(task);
      if (key) occurrences.set(key, (occurrences.get(key) || 0) + 1);
    });
    return new Set([...occurrences].filter(([, count]) => count > 1).map(([key]) => key));
  }, [tasks]);
  const counts = useMemo(() => ({
    all: tasks.length,
    active: tasks.filter((task) => activeStatuses.has(task.status)).length,
    failed: tasks.filter((task) => failedStatuses.has(task.status)).length,
    completed: tasks.filter((task) => task.status === 'completed').length,
  }), [tasks]);
  const visibleTasks = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return tasks.filter((task) => {
      const collectionKey = taskCollectionKey(task);
      const context = monitorTaskContext(task, t, Boolean(collectionKey && repeatedCollectionKeys.has(collectionKey)));
      return taskMatchesFilter(task, filter) && (!normalizedQuery || [taskTitle(task), taskSource(task), task.id, task.progress.current_filename, context?.label, context?.preview].some((value) => value?.toLowerCase().includes(normalizedQuery)));
    });
  }, [tasks, filter, query, t, repeatedCollectionKeys]);
  const selectedTask = visibleTasks.find((task) => task.id === selectedId) || visibleTasks[0] || null;

  useEffect(() => {
    if (selectedTask && selectedTask.id !== selectedId) setSelectedId(selectedTask.id);
  }, [selectedTask, selectedId]);

  if (!tasks.length) return <div className="empty-state">{t('noTasks')}</div>;
  const filters: Array<[TaskFilter, TKey]> = [['all', 'taskFilterAll'], ['active', 'taskFilterActive'], ['failed', 'taskFilterFailed'], ['completed', 'taskFilterCompleted']];

  return <div className="tasks-page">
    <div className="task-toolbar">
      <div className="task-filters" role="tablist" aria-label={t('taskStatusFilter')}>{filters.map(([value, label]) => <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)} role="tab" aria-selected={filter === value}><span>{t(label)}</span><strong>{counts[value]}</strong></button>)}</div>
      <label className="task-search"><Search aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('searchTasks')} /></label>
      <button className="task-clear" onClick={() => void clearTasks()}><Trash2 aria-hidden="true" />{t('clearRecords')}</button>
    </div>

    {!visibleTasks.length ? <div className="empty-state"><ListFilter aria-hidden="true" />{t('noMatchingTasks')}</div> : <div className="task-console">
      <div className="task-queue" role="list">{visibleTasks.map((task) => {
        const taskCounts = playlistCounts(task);
        const percent = percentFor(task, taskCounts);
        const Icon = statusIcon(task.status);
        const collectionKey = taskCollectionKey(task);
        const monitorContext = monitorTaskContext(task, t, Boolean(collectionKey && repeatedCollectionKeys.has(collectionKey)));
        return <button className={`task-queue-item task-${task.status} ${monitorContext ? 'monitor-batch' : ''} ${selectedTask?.id === task.id ? 'selected' : ''}`} key={task.id} onClick={() => setSelectedId(task.id)} role="listitem">
          <span className={`task-status-icon ${statusTone(task.status)}`}><Icon aria-hidden="true" /></span>
          <span className="task-queue-copy"><span><strong title={taskTitle(task)}>{taskTitle(task)}</strong><small>{new Date(taskTimestamp(task)).toLocaleString()}</small></span>{monitorContext && <span className="task-queue-batch"><span className="badge blue"><Radar aria-hidden="true" />{monitorContext.label}</span>{monitorContext.preview && <small title={monitorContext.preview}>{monitorContext.preview}</small>}</span>}<span className="task-queue-meta"><span>{taskSource(task)}</span><span>{Math.round(percent)}%</span>{taskCounts ? <span><ListVideo aria-hidden="true" />{taskCounts.completed}/{taskCounts.total}</span> : task.status === 'running' && task.progress.speed && <span>{task.progress.speed}</span>}</span><span className="task-queue-progress"><span style={{ width: `${percent}%` }} /></span></span>
        </button>;
      })}</div>
      {selectedTask && <TaskDetail task={selectedTask} api={api} t={t} onChanged={onChanged} onCancel={onCancel} onDelete={deleteTask} onResume={resumeTask} onRestart={restartTask} />}
    </div>}
  </div>;
}
