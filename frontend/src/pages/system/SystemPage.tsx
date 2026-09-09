import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, Download, FolderCheck, Gauge, LockKeyhole, RefreshCw, Server, Terminal } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { DependencyStatus, DependencyUpdateResponse, HealthResponse, SettingsResponse } from '../../api/types';
import type { T } from '../../i18n';

interface SystemPageProps {
  api: ApiClient;
  health: HealthResponse | null;
  settings: SettingsResponse | null;
  t: T;
  onChanged: () => void;
}

function dependencyName(dependency: DependencyStatus): string {
  return dependency.name === 'yt-dlp' ? 'yt-dlp' : 'FFmpeg';
}

function sourceLabel(dependency: DependencyStatus, t: T): string {
  if (!dependency.managed) return t('dependencySystemManaged');
  if (dependency.source === 'python-module') return t('dependencyPythonPackage');
  if (dependency.source === 'imageio-ffmpeg') return 'imageio-ffmpeg';
  return dependency.source || '-';
}

export function SystemPage({ api, health, settings, t, onChanged }: SystemPageProps) {
  const [update, setUpdate] = useState<DependencyUpdateResponse | null>(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [logsExpanded, setLogsExpanded] = useState(false);
  const logRef = useRef<HTMLPreElement>(null);

  async function loadStatus(refresh = false) {
    try {
      const status = await api.dependencyStatus(refresh);
      setUpdate(status);
      setRequestError(null);
      return status;
    } catch (err) {
      setRequestError(err instanceof Error ? err.message : String(err));
      return null;
    }
  }

  async function updateDependencies() {
    setRequestError(null);
    try {
      setUpdate(await api.updateDependencies());
    } catch (err) {
      setRequestError(err instanceof Error ? err.message : String(err));
    }
  }

  useEffect(() => { void loadStatus(); }, [api]);
  useEffect(() => {
    if (!update?.running) {
      if (update?.phase === 'completed') onChanged();
      return;
    }
    const timer = window.setInterval(() => void loadStatus(), 800);
    return () => window.clearInterval(timer);
  }, [api, update?.running, update?.phase, onChanged]);
  useEffect(() => {
    if (update?.running || update?.phase === 'failed') setLogsExpanded(true);
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [update?.logs.length, update?.running, update?.phase]);

  const updatesAvailable = useMemo(() => update?.dependencies.filter((dependency) => dependency.update_available).length || 0, [update]);
  const canRepair = Boolean(update?.dependencies.some((dependency) => dependency.managed && (!dependency.current_version || dependency.error)));
  const busy = Boolean(update?.running);
  const checked = Boolean(update && update.phase !== 'idle' && update.phase !== 'checking');
  const updateDisabled = busy || (checked && updatesAvailable === 0 && !canRepair);

  const overview = [
    { icon: Server, label: t('serviceStatus'), value: health?.healthy ? t('healthy') : t('needsAttention'), tone: health?.healthy ? 'current' : 'update' },
    { icon: FolderCheck, label: t('downloadStorage'), value: health?.download_dir_writable ? t('writable') : t('notWritable'), tone: health?.download_dir_writable ? 'current' : 'error' },
    { icon: Gauge, label: t('queueConcurrency'), value: String(settings?.queue_concurrency || '-'), tone: 'neutral' },
    { icon: LockKeyhole, label: t('serverAuthentication'), value: settings?.auth_configured ? t('enabled') : t('disabled'), tone: settings?.auth_configured ? 'current' : 'neutral' },
  ];

  return <div className="system-page">
    <section className="system-overview" aria-label={t('systemOverview')}>{overview.map(({ icon: Icon, label, value, tone }) => <div key={label}><span className={`system-overview-icon ${tone}`}><Icon aria-hidden="true" /></span><span><small>{label}</small><strong>{value}</strong></span></div>)}</section>

    <section className="dependency-console">
      <header className="dependency-header">
        <div><h2>{t('dependencyManagement')}</h2><p>{t('dependencyManagementDesc')}</p></div>
        <div className="toolbar"><button onClick={() => void loadStatus(true)} disabled={busy}><RefreshCw aria-hidden="true" />{t('checkForUpdates')}</button><button className={updatesAvailable || canRepair || busy ? 'primary' : ''} onClick={() => void updateDependencies()} disabled={updateDisabled}>{busy && update?.phase === 'updating' ? <RefreshCw className="spin" aria-hidden="true" /> : <Download aria-hidden="true" />}{busy ? t(update?.phase === 'checking' ? 'checkingUpdates' : 'updatingDependencies') : checked && updatesAvailable === 0 && !canRepair ? t('dependenciesCurrent') : updatesAvailable ? t('installUpdatesCount').replace('{count}', String(updatesAvailable)) : t('updateDependencies')}</button></div>
      </header>

      {requestError && <div className="dependency-error"><AlertCircle aria-hidden="true" />{requestError}</div>}
      <div className="dependency-list">
        {!update?.dependencies.length && <div className="dependency-placeholder"><RefreshCw className={busy ? 'spin' : ''} aria-hidden="true" />{t(busy ? 'checkingUpdates' : 'dependencyStatusUnavailable')}</div>}
        {update?.dependencies.map((dependency) => <div className="dependency-row" key={dependency.name}>
          <span className={`dependency-icon ${dependency.error ? 'error' : dependency.update_available ? 'update' : 'current'}`}>{dependency.error ? <AlertCircle aria-hidden="true" /> : dependency.update_available ? <Download aria-hidden="true" /> : <CheckCircle2 aria-hidden="true" />}</span>
          <div className="dependency-name"><strong>{dependencyName(dependency)}</strong><span>{sourceLabel(dependency, t)}</span></div>
          <div><span>{t('installedVersion')}</span><strong>{dependency.current_version || t('notInstalled')}</strong></div>
          <div><span>{t('latestVersion')}</span><strong>{dependency.latest_version || (dependency.managed ? '-' : t('dependencySystemManaged'))}</strong></div>
          <span className={`badge ${dependency.error ? 'red' : dependency.update_available ? 'amber' : 'green'}`}>{dependency.error ? t('checkFailed') : dependency.update_available ? t('updateAvailable') : dependency.managed ? t('dependenciesCurrent') : t('managedExternally')}</span>
        </div>)}
      </div>

      <button className="dependency-log-toggle" onClick={() => setLogsExpanded((value) => !value)} aria-expanded={logsExpanded}><span><Terminal aria-hidden="true" /><strong>{t('updateOutput')}</strong><span className={`badge ${update?.phase === 'failed' ? 'red' : busy ? 'amber' : update?.phase === 'completed' ? 'green' : ''}`}>{t(({
        idle: 'dependencyIdle', checking: 'checkingUpdates', ready: 'checkCompleted', updating: 'updatingDependencies', completed: 'updateCompleted', failed: 'statusFailed',
      } as const)[update?.phase || 'idle'])}</span></span>{logsExpanded ? <ChevronUp aria-hidden="true" /> : <ChevronDown aria-hidden="true" />}</button>
      {logsExpanded && <pre className="dependency-log" ref={logRef}>{update?.logs.length ? update.logs.join('\n') : t('waitingForDependencyCheck')}</pre>}
    </section>

    <section className="runtime-config">
      <header><h2>{t('runtimeConfiguration')}</h2><p>{t('runtimeConfigurationDesc')}</p></header>
      <dl><div><dt>{t('downloadDir')}</dt><dd title={settings?.download_dir}>{settings?.download_dir || '-'}</dd></div><div><dt>{t('configDir')}</dt><dd title={settings?.config_dir}>{settings?.config_dir || '-'}</dd></div><div><dt>{t('queueConcurrency')}</dt><dd>{settings?.queue_concurrency || '-'}</dd></div><div><dt>{t('serverAuthentication')}</dt><dd>{settings?.auth_configured ? t('enabled') : t('disabled')}</dd></div></dl>
    </section>
  </div>;
}
