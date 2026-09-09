import { Check, ChevronDown, ChevronUp, Circle, Download, RefreshCw, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { PlaylistEntry, TaskResponse } from '../../api/types';
import type { T, TKey } from '../../i18n';
import { formatBytes, formatPageInfo } from '../../shared/format';
import { paginationItems } from '../../shared/pagination';

type PlaylistItemState = 'pending' | 'downloading' | 'completed' | 'failed';

function taskPlaylistEntries(task: TaskResponse): PlaylistEntry[] {
  const entries = task.options.playlist_entries;
  return Array.isArray(entries) ? entries.filter((entry): entry is PlaylistEntry => typeof entry === 'object' && entry !== null && typeof (entry as PlaylistEntry).index === 'number') : [];
}

function playlistItemState(task: TaskResponse, entry: PlaylistEntry): PlaylistItemState {
  if (new Set(task.progress.playlist_failed_indexes || []).has(entry.index)) return 'failed';
  if (new Set(task.progress.playlist_completed_indexes || []).has(entry.index)) return 'completed';
  const currentIndex = task.progress.playlist_current_index;
  if (currentIndex === entry.index) return 'downloading';
  if (task.status === 'completed') return 'completed';
  if (!task.progress.playlist_completed_indexes && currentIndex && entry.index < currentIndex) return 'completed';
  return 'pending';
}

function stateLabel(state: PlaylistItemState, t: T): string {
  const labels: Record<PlaylistItemState, TKey> = {
    pending: 'itemPending',
    downloading: 'itemDownloading',
    completed: 'itemCompleted',
    failed: 'itemFailed',
  };
  return t(labels[state]);
}

function currentFilename(path: string | null | undefined): string | null {
  if (!path) return null;
  return path.split(/[\\/]/).pop() || path;
}

function StateIcon({ state }: { state: PlaylistItemState }) {
  const Icon = { pending: Circle, downloading: Download, completed: Check, failed: X }[state];
  return <Icon aria-hidden="true" />;
}

interface TaskPlaylistProps {
  task: TaskResponse;
  api: ApiClient;
  t: T;
  onChanged: () => void | Promise<void>;
}

export function TaskPlaylist({ task, api, t, onChanged }: TaskPlaylistProps) {
  const entries = taskPlaylistEntries(task);
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(entries.length / pageSize));
  const currentEntryPosition = entries.findIndex((entry) => entry.index === task.progress.playlist_current_index);
  const currentEntryPage = currentEntryPosition >= 0 ? Math.floor(currentEntryPosition / pageSize) + 1 : null;
  const [expanded, setExpanded] = useState(() => task.status === 'running');
  const [page, setPage] = useState(() => currentEntryPage || 1);
  const listRef = useRef<HTMLDivElement>(null);
  const normalizedPage = Math.min(pageCount, Math.max(1, page));
  const visibleEntries = entries.slice((normalizedPage - 1) * pageSize, normalizedPage * pageSize);
  const pageItems = paginationItems(normalizedPage, pageCount);

  useEffect(() => {
    if (task.status === 'running') setExpanded(true);
  }, [task.status]);
  useEffect(() => {
    if (currentEntryPage) setPage(currentEntryPage);
  }, [currentEntryPage]);
  useEffect(() => {
    if (page > pageCount) setPage(pageCount);
  }, [page, pageCount]);
  useEffect(() => {
    setPage(currentEntryPage || 1);
    listRef.current?.scrollTo({ top: 0 });
  }, [task.id]);

  function changePage(nextPage: number) {
    setPage(Math.min(pageCount, Math.max(1, nextPage)));
    listRef.current?.scrollTo({ top: 0 });
  }

  if (!entries.length) return null;
  async function retryItem(entry: PlaylistEntry) {
    await api.retryPlaylistItem(task.id, entry.index);
    await onChanged();
  }
  const counts = entries.reduce<Record<PlaylistItemState, number>>((result, entry) => {
    result[playlistItemState(task, entry)] += 1;
    return result;
  }, { pending: 0, downloading: 0, completed: 0, failed: 0 });

  return <div className={`task-playlist ${expanded ? 'expanded' : ''}`}>
    <button className="task-playlist-toggle" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
      <span><strong>{t('taskPlaylist')}</strong><small>{counts.completed} {t('itemCompleted')} · {counts.pending} {t('itemPending')}{counts.failed > 0 ? ` · ${counts.failed} ${t('itemFailed')}` : ''}</small></span>
      {expanded ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}
    </button>
    {expanded && <>
      <div className="task-playlist-list" ref={listRef}>{visibleEntries.map((entry) => {
        const state = playlistItemState(task, entry);
        const failure = task.progress.playlist_failures?.[String(entry.index)];
        const live = state === 'downloading';
        const itemPercent = live && task.progress.percent != null ? Math.max(0, Math.min(100, task.progress.percent)) : null;
        const size = live && (task.progress.downloaded_bytes || task.progress.total_bytes)
          ? `${formatBytes(task.progress.downloaded_bytes)}${task.progress.total_bytes ? ` / ${formatBytes(task.progress.total_bytes)}` : ''}`
          : null;
        const metrics = live ? [itemPercent != null ? `${itemPercent.toFixed(1)}%` : null, size, task.progress.speed, task.progress.eta ? `${t('eta')} ${task.progress.eta}` : null].filter(Boolean) : [];
        const filename = live ? currentFilename(task.progress.current_filename) : null;
        return <div key={entry.index} className={`task-playlist-item ${state}`}>
          <span className="task-playlist-index">{entry.index}</span>
          <span className="task-playlist-state" title={stateLabel(state, t)}><StateIcon state={state} /></span>
          <span className="task-playlist-copy"><strong>{entry.title || entry.id || entry.url || '-'}</strong>{failure && <small className="task-playlist-failure">{failure}</small>}{filename && <small className="task-playlist-filename" title={task.progress.current_filename || undefined}>{filename}</small>}{live && <span className="task-playlist-live"><span className="task-playlist-item-progress" role="progressbar" aria-valuenow={itemPercent ?? undefined} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${itemPercent || 0}%` }} /></span>{metrics.length > 0 && <small>{metrics.map((metric) => <span key={metric}>{metric}</span>)}</small>}</span>}</span>
          <span className={`badge ${state === 'completed' ? 'green' : state === 'downloading' ? 'blue' : state === 'failed' ? 'red' : ''}`}>{live && itemPercent != null ? `${Math.round(itemPercent)}%` : stateLabel(state, t)}</span>
          {state === 'failed' && <button className="icon-button" title={t('retryItem')} aria-label={t('retryItem')} onClick={() => void retryItem(entry)}><RefreshCw aria-hidden="true" /></button>}
        </div>;
      })}</div>
      {pageCount > 1 && <div className="task-playlist-pagination">
        <span className="muted">{formatPageInfo(t('taskPlaylistPageInfo'), normalizedPage, pageCount, entries.length)}</span>
        <div className="page-list compact-page-list" aria-label="Pagination">{pageItems.map((item, index) => item === 'ellipsis' ? <span className="page-ellipsis" key={`task-playlist-ellipsis-${index}`}>...</span> : <button className={item === normalizedPage ? 'active' : ''} key={item} onClick={() => changePage(item)} disabled={item === normalizedPage} aria-current={item === normalizedPage ? 'page' : undefined}>{item}</button>)}</div>
        <div className="toolbar"><button onClick={() => changePage(normalizedPage - 1)} disabled={normalizedPage <= 1}>{t('previousPage')}</button><button onClick={() => changePage(normalizedPage + 1)} disabled={normalizedPage >= pageCount}>{t('nextPage')}</button></div>
      </div>}
    </>}
  </div>;
}
