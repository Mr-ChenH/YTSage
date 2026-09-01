import { useEffect, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { PlaylistEntry, TaskResponse } from '../../api/types';
import type { T, TKey } from '../../i18n';
import { formatPageInfo } from '../../shared/format';
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

function stateTone(state: PlaylistItemState): string {
  return { pending: '', downloading: 'blue', completed: 'green', failed: 'red' }[state];
}

interface TaskPlaylistProps {
  task: TaskResponse;
  api: ApiClient;
  t: T;
  onChanged: () => void;
}

export function TaskPlaylist({ task, api, t, onChanged }: TaskPlaylistProps) {
  const entries = taskPlaylistEntries(task);
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(entries.length / pageSize));
  const currentEntryPosition = entries.findIndex((entry) => entry.index === task.progress.playlist_current_index);
  const currentEntryPage = currentEntryPosition >= 0 ? Math.floor(currentEntryPosition / pageSize) + 1 : null;
  const [expanded, setExpanded] = useState(() => task.status === 'running' || task.status === 'queued');
  const [page, setPage] = useState(() => currentEntryPage || 1);
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

  if (!entries.length) return null;
  async function retryItem(entry: PlaylistEntry) {
    await api.retryPlaylistItem(task.id, entry.index);
    onChanged();
  }
  const counts = entries.reduce<Record<PlaylistItemState, number>>((result, entry) => {
    result[playlistItemState(task, entry)] += 1;
    return result;
  }, { pending: 0, downloading: 0, completed: 0, failed: 0 });

  return <div className="task-playlist">
    <div className="section-heading"><h3>{t('taskPlaylist')}</h3><div className="toolbar"><span className="badge blue">{entries.length}</span><span className="badge green">{t('itemCompleted')}: {counts.completed}</span><span className="badge red">{t('itemFailed')}: {counts.failed}</span><button onClick={() => setExpanded((value) => !value)}>{expanded ? t('collapse') : t('expand')}</button></div></div>
    {expanded && <>
      <div className="task-playlist-list">{visibleEntries.map((entry) => {
        const state = playlistItemState(task, entry);
        const failure = task.progress.playlist_failures?.[String(entry.index)];
        return <div key={entry.index} className={`task-playlist-item ${state === 'downloading' ? 'current' : ''}`} title={failure || undefined}>
          <span className="badge">{entry.index}</span><strong>{entry.title || entry.id || entry.url || '-'}</strong><span className={`badge ${stateTone(state)}`}>{stateLabel(state, t)}</span>{state === 'failed' && <button onClick={() => void retryItem(entry)}>{t('retryItem')}</button>}
        </div>;
      })}</div>
      {pageCount > 1 && <div className="task-playlist-pagination">
        <span className="muted">{formatPageInfo(t('taskPlaylistPageInfo'), normalizedPage, pageCount, entries.length)}</span>
        <div className="page-list compact-page-list" aria-label="Pagination">{pageItems.map((item, index) => item === 'ellipsis' ? <span className="page-ellipsis" key={`task-playlist-ellipsis-${index}`}>...</span> : <button className={item === normalizedPage ? 'active' : ''} key={item} onClick={() => setPage(item)} disabled={item === normalizedPage} aria-current={item === normalizedPage ? 'page' : undefined}>{item}</button>)}</div>
        <div className="toolbar"><button onClick={() => setPage(Math.max(1, normalizedPage - 1))} disabled={normalizedPage <= 1}>{t('previousPage')}</button><button onClick={() => setPage(Math.min(pageCount, normalizedPage + 1))} disabled={normalizedPage >= pageCount}>{t('nextPage')}</button></div>
      </div>}
    </>}
  </div>;
}
