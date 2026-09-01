import { useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { HealthResponse, SettingsResponse } from '../../api/types';
import type { T } from '../../i18n';

interface SystemPageProps {
  api: ApiClient;
  health: HealthResponse | null;
  settings: SettingsResponse | null;
  t: T;
  onChanged: () => void;
}

export function SystemPage({ api, health, settings, t, onChanged }: SystemPageProps) {
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
