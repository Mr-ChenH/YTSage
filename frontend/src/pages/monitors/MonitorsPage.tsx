import { AlertCircle, Check, Clock3, ExternalLink, ListFilter, Pause, Play, RefreshCw, Save, Search, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { PlaylistMonitorResponse } from '../../api/types';
import type { T, TKey } from '../../i18n';

interface MonitorsPageProps {
  api: ApiClient;
  t: T;
}

type MonitorFilter = 'all' | 'enabled' | 'paused' | 'error';

function localTime(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : '-';
}

function monitorSource(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

function monitorMatchesFilter(monitor: PlaylistMonitorResponse, filter: MonitorFilter): boolean {
  if (filter === 'enabled') return monitor.enabled && !monitor.last_error;
  if (filter === 'paused') return !monitor.enabled;
  if (filter === 'error') return Boolean(monitor.last_error);
  return true;
}

function nextCheckText(monitor: PlaylistMonitorResponse, t: T): string {
  if (!monitor.enabled) return t('monitorPaused');
  const next = new Date(monitor.next_check_at).getTime();
  const difference = next - Date.now();
  if (!Number.isFinite(difference) || difference <= 0) return t('monitorCheckDue');
  const minutes = Math.ceil(difference / 60_000);
  if (minutes < 60) return t('monitorNextInMinutes').replace('{count}', String(minutes));
  const hours = Math.ceil(minutes / 60);
  if (hours < 24) return t('monitorNextInHours').replace('{count}', String(hours));
  return t('monitorNextInDays').replace('{count}', String(Math.ceil(hours / 24)));
}

function downloadOption(monitor: PlaylistMonitorResponse, key: string): string | null {
  const value = monitor.download_options[key];
  return typeof value === 'string' && value ? value : null;
}

interface MonitorDetailProps {
  monitor: PlaylistMonitorResponse;
  interval: number;
  busy: boolean;
  t: T;
  onInterval: (value: number) => void;
  onSaveInterval: () => void;
  onCheck: () => void;
  onToggle: () => void;
  onDelete: () => void;
}

function MonitorDetail({ monitor, interval, busy, t, onInterval, onSaveInterval, onCheck, onToggle, onDelete }: MonitorDetailProps) {
  const intervalChanged = interval !== monitor.interval_minutes;
  const mode = downloadOption(monitor, 'mode');
  const resolution = downloadOption(monitor, 'format_id') || t('autoBestFormat');
  return <section className="monitor-detail">
    <header className="monitor-detail-header">
      <div className="monitor-detail-title"><span className={`monitor-status-icon ${monitor.last_error ? 'error' : monitor.enabled ? 'enabled' : 'paused'}`}>{monitor.last_error ? <AlertCircle aria-hidden="true" /> : monitor.enabled ? <RefreshCw aria-hidden="true" /> : <Pause aria-hidden="true" />}</span><div><div><h2>{monitor.title || monitor.url}</h2><span className={`badge ${monitor.last_error ? 'red' : monitor.enabled ? 'green' : ''}`}>{t(monitor.last_error ? 'monitorNeedsAttention' : monitor.enabled ? 'monitorEnabled' : 'monitorPaused')}</span></div><a href={monitor.url} target="_blank" rel="noreferrer">{monitorSource(monitor.url)}<ExternalLink aria-hidden="true" /></a></div></div>
      <div className="monitor-actions"><button onClick={onCheck} disabled={busy} title={t('monitorCheckNow')}><RefreshCw aria-hidden="true" />{t('monitorCheckNow')}</button><button onClick={onToggle} disabled={busy}>{monitor.enabled ? <Pause aria-hidden="true" /> : <Play aria-hidden="true" />}{t(monitor.enabled ? 'monitorPause' : 'monitorResume')}</button><button className="danger" onClick={onDelete} disabled={busy} title={t('deleteRecord')}><Trash2 aria-hidden="true" /></button></div>
    </header>

    <div className="monitor-schedule-strip">
      <div><span>{t('monitorNextCheck')}</span><strong>{nextCheckText(monitor, t)}</strong><small>{localTime(monitor.next_check_at)}</small></div>
      <Clock3 aria-hidden="true" />
      <div><span>{t('monitorLastCheck')}</span><strong>{localTime(monitor.last_checked_at)}</strong><small>{monitor.last_checked_at ? t('monitorCheckCompleted') : t('monitorNeverChecked')}</small></div>
    </div>

    <div className="monitor-facts">
      <div><span>{t('monitorKnownItems')}</span><strong>{monitor.seen_entry_keys.length}</strong></div>
      <div><span>{t('monitorInterval')}</span><strong>{monitor.interval_minutes} {t('minutes')}</strong></div>
      <div><span>{t('monitorDownloadMode')}</span><strong>{mode ? t(({ video: 'modeVideo', audio: 'modeAudio', subtitles: 'modeSubtitles' } as Record<string, TKey>)[mode] || 'modeVideo') : '-'}</strong></div>
      <div><span>{t('resolution')}</span><strong>{resolution}</strong></div>
      <div><span>{t('monitorLastTask')}</span><strong title={monitor.last_task_id || undefined}>{monitor.last_task_id ? `#${monitor.last_task_id.slice(0, 8)}` : '-'}</strong></div>
      <div><span>{t('createdAt')}</span><strong>{localTime(monitor.created_at)}</strong></div>
    </div>

    {monitor.last_error && <div className="monitor-error"><AlertCircle aria-hidden="true" /><div><strong>{t('monitorLastError')}</strong><p>{monitor.last_error}</p></div></div>}

    <div className="monitor-interval-editor"><div><strong>{t('monitorInterval')}</strong><span>{t('monitorIntervalHint')}</span></div><div><input aria-label={t('monitorInterval')} type="number" min="5" max="10080" value={interval} disabled={busy} onChange={(event) => onInterval(Math.max(5, Math.min(10080, Number(event.target.value) || 5)))} /><span>{t('minutes')}</span><button className="primary" onClick={onSaveInterval} disabled={busy || !intervalChanged}><Save aria-hidden="true" />{t('saveSettings')}</button></div></div>

    <div className="monitor-identity"><span>{t('monitorId')}</span><code>{monitor.id}</code></div>
  </section>;
}

export function MonitorsPage({ api, t }: MonitorsPageProps) {
  const [monitors, setMonitors] = useState<PlaylistMonitorResponse[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<MonitorFilter>('all');
  const [query, setQuery] = useState('');
  const [intervalDrafts, setIntervalDrafts] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      setMonitors(await api.monitors());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoaded(true);
    }
  }

  async function run(id: string, action: () => Promise<PlaylistMonitorResponse | void>) {
    setBusyId(id);
    setError(null);
    try {
      await action();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyId(null);
    }
  }

  function saveInterval(monitor: PlaylistMonitorResponse) {
    const interval = intervalDrafts[monitor.id] ?? monitor.interval_minutes;
    void run(monitor.id, async () => {
      await api.updateMonitor(monitor.id, { interval_minutes: interval });
      setIntervalDrafts((current) => {
        const next = { ...current };
        delete next[monitor.id];
        return next;
      });
    });
  }

  useEffect(() => { void load(); }, [api]);

  const counts = useMemo(() => ({
    all: monitors.length,
    enabled: monitors.filter((monitor) => monitor.enabled && !monitor.last_error).length,
    paused: monitors.filter((monitor) => !monitor.enabled).length,
    error: monitors.filter((monitor) => monitor.last_error).length,
  }), [monitors]);
  const visibleMonitors = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return monitors.filter((monitor) => monitorMatchesFilter(monitor, filter) && (!normalizedQuery || [monitor.title, monitor.url, monitor.id].some((value) => value?.toLowerCase().includes(normalizedQuery))));
  }, [monitors, filter, query]);
  const selectedMonitor = visibleMonitors.find((monitor) => monitor.id === selectedId) || visibleMonitors[0] || null;

  useEffect(() => {
    if (selectedMonitor && selectedMonitor.id !== selectedId) setSelectedId(selectedMonitor.id);
  }, [selectedMonitor, selectedId]);

  if (!loaded) return <div className="empty-state">{t('working')}</div>;
  if (!monitors.length && !error) return <div className="empty-state">{t('noMonitors')}</div>;
  const filters: Array<[MonitorFilter, TKey]> = [['all', 'monitorFilterAll'], ['enabled', 'monitorFilterEnabled'], ['paused', 'monitorFilterPaused'], ['error', 'monitorFilterError']];

  return <div className="monitors-page">
    <div className="monitor-toolbar">
      <div className="monitor-filters" role="tablist" aria-label={t('monitorStatusFilter')}>{filters.map(([value, label]) => <button key={value} className={filter === value ? 'active' : ''} onClick={() => setFilter(value)} role="tab" aria-selected={filter === value}><span>{t(label)}</span><strong>{counts[value]}</strong></button>)}</div>
      <label className="monitor-search"><Search aria-hidden="true" /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={t('searchMonitors')} /></label>
    </div>
    {error && <div className="monitor-page-error"><AlertCircle aria-hidden="true" />{error}</div>}
    {!visibleMonitors.length ? <div className="empty-state"><ListFilter aria-hidden="true" />{t('noMatchingMonitors')}</div> : <div className="monitor-console">
      <div className="monitor-list" role="list">{visibleMonitors.map((monitor) => <button className={`monitor-list-item ${selectedMonitor?.id === monitor.id ? 'selected' : ''}`} key={monitor.id} onClick={() => setSelectedId(monitor.id)} role="listitem">
        <span className={`monitor-status-icon ${monitor.last_error ? 'error' : monitor.enabled ? 'enabled' : 'paused'}`}>{monitor.last_error ? <AlertCircle aria-hidden="true" /> : monitor.enabled ? <Check aria-hidden="true" /> : <Pause aria-hidden="true" />}</span>
        <span className="monitor-list-copy"><span><strong>{monitor.title || monitor.url}</strong><small>{monitor.seen_entry_keys.length}</small></span><span><span>{monitorSource(monitor.url)}</span><span>{nextCheckText(monitor, t)}</span></span></span>
      </button>)}</div>
      {selectedMonitor && <MonitorDetail monitor={selectedMonitor} interval={intervalDrafts[selectedMonitor.id] ?? selectedMonitor.interval_minutes} busy={busyId === selectedMonitor.id} t={t} onInterval={(value) => setIntervalDrafts((current) => ({ ...current, [selectedMonitor.id]: value }))} onSaveInterval={() => saveInterval(selectedMonitor)} onCheck={() => void run(selectedMonitor.id, () => api.checkMonitor(selectedMonitor.id))} onToggle={() => void run(selectedMonitor.id, () => api.updateMonitor(selectedMonitor.id, { enabled: !selectedMonitor.enabled }))} onDelete={() => window.confirm(t('confirmDeleteMonitor')) && void run(selectedMonitor.id, () => api.deleteMonitor(selectedMonitor.id))} />}
    </div>}
  </div>;
}
