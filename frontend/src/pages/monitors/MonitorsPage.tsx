import { useEffect, useState } from 'react';
import { Pause, Play, RefreshCw, Trash2 } from 'lucide-react';
import type { ApiClient } from '../../api/client';
import type { PlaylistMonitorResponse } from '../../api/types';
import type { T } from '../../i18n';

interface MonitorsPageProps {
  api: ApiClient;
  t: T;
}

function localTime(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : '-';
}

export function MonitorsPage({ api, t }: MonitorsPageProps) {
  const [monitors, setMonitors] = useState<PlaylistMonitorResponse[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setError(null);
    try {
      setMonitors(await api.monitors());
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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

  useEffect(() => { void load(); }, [api]);

  return <div className="stack">
    {error && <p className="error-line">{error}</p>}
    {!monitors.length && <div className="empty-state">{t('noMonitors')}</div>}
    <div className="list">{monitors.map((monitor) => <div className="row" key={monitor.id}>
      <div className="row-top">
        <div className="stack"><strong>{monitor.title || monitor.url}</strong><span className="muted">{monitor.url}</span></div>
        <span className={`badge ${monitor.enabled ? 'green' : ''}`}>{t(monitor.enabled ? 'monitorEnabled' : 'monitorPaused')}</span>
      </div>
      <div className="detail-list monitor-details">
        <div className="detail-row"><span>{t('monitorKnownItems')}</span><strong>{monitor.seen_entry_keys.length}</strong></div>
        <div className="detail-row"><span>{t('monitorLastCheck')}</span><strong>{localTime(monitor.last_checked_at)}</strong></div>
        <div className="detail-row"><span>{t('monitorNextCheck')}</span><strong>{localTime(monitor.next_check_at)}</strong></div>
        <div className="detail-row"><span>{t('monitorLastTask')}</span><strong>{monitor.last_task_id || '-'}</strong></div>
      </div>
      {monitor.last_error && <p className="error-line">{monitor.last_error}</p>}
      <div className="toolbar">
        <label>{t('monitorInterval')}<input type="number" min="5" max="10080" value={monitor.interval_minutes} disabled={busyId === monitor.id} onChange={(event) => {
          const interval = Math.max(5, Math.min(10080, Number(event.target.value) || 5));
          setMonitors((current) => current.map((item) => item.id === monitor.id ? { ...item, interval_minutes: interval } : item));
        }} onBlur={() => void run(monitor.id, () => api.updateMonitor(monitor.id, { interval_minutes: monitor.interval_minutes }))} /></label>
        <button onClick={() => void run(monitor.id, () => api.checkMonitor(monitor.id))} disabled={busyId === monitor.id} title={t('monitorCheckNow')}><RefreshCw size={16} />{t('monitorCheckNow')}</button>
        <button onClick={() => void run(monitor.id, () => api.updateMonitor(monitor.id, { enabled: !monitor.enabled }))} disabled={busyId === monitor.id}>{monitor.enabled ? <Pause size={16} /> : <Play size={16} />}{t(monitor.enabled ? 'monitorPause' : 'monitorResume')}</button>
        <button className="danger" onClick={() => window.confirm(t('confirmDeleteMonitor')) && void run(monitor.id, () => api.deleteMonitor(monitor.id))} disabled={busyId === monitor.id}><Trash2 size={16} />{t('deleteRecord')}</button>
      </div>
    </div>)}</div>
  </div>;
}
