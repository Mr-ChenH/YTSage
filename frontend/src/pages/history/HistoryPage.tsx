import { Check, Copy, ExternalLink, FileAudio, FileQuestion, FileText, FileVideo, FolderOpen, History, RefreshCw, Search, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { HistoryEntry, MediaType, TaskResponse } from '../../api/types';
import type { T, TKey } from '../../i18n';
import { formatBytes, mediaLabel, statusLabel, statusTone } from '../../shared/format';
import { paginationItems } from '../../shared/pagination';

interface HistoryPageProps {
  api: ApiClient;
  t: T;
  onOpenFiles: () => void;
  onTask: (task: TaskResponse) => void;
  refreshKey: number;
}

type HistoryFilter = 'all' | MediaType;
const pageSize = 15;

function entrySource(entry: HistoryEntry): string {
  if (!entry.url) return '-';
  try {
    return new URL(entry.url).hostname.replace(/^www\./, '');
  } catch {
    return entry.url;
  }
}

function entryFilename(entry: HistoryEntry): string {
  if (!entry.output_path) return entry.title || entry.id;
  return entry.output_path.split(/[\\/]/).pop() || entry.output_path;
}

function mediaIcon(type: MediaType) {
  if (type === 'video') return FileVideo;
  if (type === 'audio') return FileAudio;
  if (type === 'subtitle') return FileText;
  return FileQuestion;
}

export function HistoryPage({ api, t, onOpenFiles, onTask, refreshKey }: HistoryPageProps) {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<HistoryFilter>('all');
  const [query, setQuery] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);

  async function load(targetPage = page, targetQuery = searchQuery, targetFilter = filter) {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const result = await api.searchHistory((targetPage - 1) * pageSize, pageSize, targetQuery, '', targetFilter === 'all' ? '' : targetFilter);
      if (currentRequest !== requestId.current) return;
      setEntries(result.items);
      setTotal(result.total);
    } catch (err) {
      if (currentRequest === requestId.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [api, page, searchQuery, filter, refreshKey]);
  const selected = entries.find((entry) => entry.id === selectedId) || entries[0] || null;
  useEffect(() => {
    if (selected && selected.id !== selectedId) setSelectedId(selected.id);
    setCopied(false);
  }, [selected, selectedId]);

  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const pageItems = useMemo(() => paginationItems(page, pageCount), [page, pageCount]);
  const filters: Array<[HistoryFilter, TKey]> = [['all', 'historyFilterAll'], ['video', 'mediaVideo'], ['audio', 'mediaAudio'], ['subtitle', 'mediaSubtitle']];

  async function deleteHistory(id: string) {
    setBusyId(id);
    try {
      await api.deleteHistory(id);
      if (entries.length === 1 && page > 1) setPage(page - 1);
      else await load();
    } finally {
      setBusyId(null);
    }
  }

  async function clearHistory() {
    if (!window.confirm(t('confirmClearHistory'))) return;
    await api.clearHistory();
    setPage(1);
    await load(1);
  }

  async function redownload(entry: HistoryEntry) {
    setBusyId(entry.id);
    setError(null);
    try {
      onTask(await api.redownloadHistory(entry.id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  async function copyPath(path: string) {
    await navigator.clipboard.writeText(path);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }

  function submitSearch() {
    setPage(1);
    setSearchQuery(query.trim());
  }

  return <div className="history-page">
    <div className="history-toolbar">
      <div className="history-filters" role="tablist" aria-label={t('historyMediaFilter')}>{filters.map(([value, label]) => <button key={value} className={filter === value ? 'active' : ''} onClick={() => { setFilter(value); setPage(1); }} role="tab" aria-selected={filter === value}>{t(label)}</button>)}</div>
      <form className="history-search" onSubmit={(event) => { event.preventDefault(); submitSearch(); }}><Search aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('searchHistory')} /><button type="submit">{t('search')}</button></form>
      <button className="history-clear" onClick={() => void clearHistory()} disabled={!total}><Trash2 aria-hidden="true" />{t('clearRecords')}</button>
    </div>
    {error && <div className="history-error">{error}</div>}
    {loading && !entries.length ? <div className="empty-state">{t('working')}</div> : !entries.length ? <div className="empty-state"><History aria-hidden="true" />{searchQuery || filter !== 'all' ? t('noMatchingHistory') : t('noHistory')}</div> : <div className="history-console">
      <div className="history-list" role="list">{entries.map((entry) => { const Icon = mediaIcon(entry.media_type); return <button key={entry.id} className={`history-item ${selected?.id === entry.id ? 'selected' : ''}`} onClick={() => setSelectedId(entry.id)} role="listitem"><span className={`history-media-icon ${entry.media_type}`}><Icon aria-hidden="true" /></span><span className="history-item-copy"><strong title={entry.title || entryFilename(entry)}>{entry.title || entryFilename(entry)}</strong><span><span>{entrySource(entry)}</span><span>{formatBytes(entry.file_size)}</span></span><small>{new Date(entry.downloaded_at).toLocaleString()}</small></span><span className={`history-result ${statusTone(entry.status)}`} title={statusLabel(entry.status, t)} /></button>; })}</div>
      {selected && <section className="history-detail">
        <header><div className="history-detail-title"><span className={`history-media-icon ${selected.media_type}`}>{(() => { const Icon = mediaIcon(selected.media_type); return <Icon aria-hidden="true" />; })()}</span><div><div><h2>{selected.title || entryFilename(selected)}</h2><span className={`badge ${statusTone(selected.status)}`}>{statusLabel(selected.status, t)}</span></div><p>{entryFilename(selected)}</p></div></div><button className="danger" onClick={() => void deleteHistory(selected.id)} disabled={busyId === selected.id} title={t('deleteRecord')}><Trash2 aria-hidden="true" /></button></header>
        <dl className="history-facts"><div><dt>{t('type')}</dt><dd>{mediaLabel(selected.media_type, t)}</dd></div><div><dt>{t('size')}</dt><dd>{formatBytes(selected.file_size)}</dd></div><div><dt>{t('downloadedAt')}</dt><dd>{new Date(selected.downloaded_at).toLocaleString()}</dd></div><div><dt>{t('taskSource')}</dt><dd>{entrySource(selected)}</dd></div></dl>
        {selected.output_path && <div className="history-path"><span>{t('outputFile')}</span><strong title={selected.output_path}>{selected.output_path}</strong><button onClick={() => void copyPath(selected.output_path!)} title={t('copyPath')}>{copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}</button></div>}
        {selected.url && <div className="history-source"><span>{t('originalUrl')}</span><a href={selected.url} target="_blank" rel="noreferrer" title={selected.url}>{selected.url}</a><a className="icon-button" href={selected.url} target="_blank" rel="noreferrer" title={t('openSourceLink')}><ExternalLink aria-hidden="true" /></a></div>}
        <div className="history-actions"><button className="primary" onClick={onOpenFiles}><FolderOpen aria-hidden="true" />{t('openFiles')}</button><button onClick={() => void redownload(selected)} disabled={!selected.task_id || busyId === selected.id}><RefreshCw aria-hidden="true" />{busyId === selected.id ? t('working') : t('redownload')}</button></div>
        <div className="history-identity"><span>{t('historyId')}</span><code>{selected.id}</code>{selected.task_id && <><span>{t('taskId')}</span><code>{selected.task_id}</code></>}</div>
      </section>}
    </div>}
    {!!entries.length && <div className="history-pagination"><span>{t('historyResultCount').replace('{count}', String(total))}</span><div className="page-list">{pageItems.map((item, index) => item === 'ellipsis' ? <span className="page-ellipsis" key={`history-${index}`}>...</span> : <button key={item} className={item === page ? 'active' : ''} onClick={() => setPage(item)} disabled={item === page}>{item}</button>)}</div><button onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}>{t('previousPage')}</button><button onClick={() => setPage(Math.min(pageCount, page + 1))} disabled={page >= pageCount}>{t('nextPage')}</button></div>}
  </div>;
}
