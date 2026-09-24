import { ChevronDown, ClipboardPaste, Download, ListVideo, LoaderCircle, Radar, Settings2, SlidersHorizontal, Sparkles } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../../api/client';
import type { CreateTaskRequest, DownloadMode, Platform, PlatformAccount, SettingsResponse, TaskResponse } from '../../api/types';
import { filenameTemplatePresets } from '../../config/download';
import type { T, TKey } from '../../i18n';
import { AnalysisDetails } from './AnalysisDetails';
import { AnalysisSummary } from './AnalysisSummary';
import {
  bestVideoFormat,
  formatLabel,
  modeFormats,
  playlistItemsValue,
  preferredFormatForMode,
  rawText,
  selectedPlaylistEntries,
  taskFilenameTemplate,
  toggleListItem,
} from './workspaceUtils';
import type { WorkspaceState } from './workspaceState';

interface WorkspacePageProps {
  api: ApiClient;
  t: T;
  settings: SettingsResponse | null;
  state: WorkspaceState;
  onState: (state: WorkspaceState) => void;
  onTask: (task: TaskResponse) => void;
}

function modeLabel(mode: DownloadMode, t: T): string {
  const labels: Record<DownloadMode, TKey> = { video: 'modeVideo', audio: 'modeAudio', subtitles: 'modeSubtitles' };
  return t(labels[mode]);
}

function qualityLabel(resolution: string | null | undefined, t: T): string {
  if (!resolution) return t('unknownResolution');
  const dimensions = resolution.match(/(\d+)\s*x\s*(\d+)/i);
  const height = dimensions ? Number(dimensions[2]) : Number(resolution.match(/(\d+)p/i)?.[1] || 0);
  const quality = height >= 2160 ? '4K' : height >= 1440 ? '2K' : height >= 1080 ? 'Full HD' : height >= 720 ? 'HD' : height ? `${height}p` : '';
  return quality ? `${quality} (${resolution})` : resolution;
}

function friendlyCodec(codec: string | null | undefined): string | null {
  if (!codec || codec === 'none') return null;
  const normalized = codec.toLowerCase();
  if (normalized.startsWith('av01')) return 'AV1';
  if (normalized.startsWith('avc1') || normalized.startsWith('h264')) return 'H.264';
  if (normalized.startsWith('hev1') || normalized.startsWith('hvc1') || normalized.startsWith('h265')) return 'H.265';
  if (normalized.startsWith('vp9') || normalized.startsWith('vp09')) return 'VP9';
  if (normalized.startsWith('mp4a')) return 'AAC';
  if (normalized.startsWith('opus')) return 'Opus';
  return codec;
}

function videoSpecification(format: ReturnType<typeof bestVideoFormat>, t: T): string {
  if (!format) return '-';
  const parts = [format.fps ? `${format.fps} FPS` : null, friendlyCodec(format.video_codec), format.ext?.toUpperCase()].filter(Boolean);
  return parts.length ? parts.join(' · ') : t('formatDetailsUnavailable');
}

function accountPlatformForUrl(value: string): Platform | null {
  let host: string;
  try {
    host = new URL(value).hostname.toLowerCase();
  } catch {
    return null;
  }
  const matches = (domain: string) => host === domain || host.endsWith(`.${domain}`);
  if (matches('bilibili.com') || matches('b23.tv')) return 'bilibili';
  if (matches('douyin.com') || matches('iesdouyin.com')) return 'douyin';
  return null;
}

function accountCanDownload(account: PlatformAccount): boolean {
  if (!account.cookie_status.usable || account.state === 'invalid' || account.state === 'expired') return false;
  return account.platform === 'douyin' || account.state === 'valid';
}

const analysisErrorKeys = {
  fresh_cookies_required: 'douyinFreshCookiesRequired',
  provider_risk_control: 'douyinRiskControl',
  provider_timeout: 'douyinProviderTimeout',
  provider_unavailable: 'douyinProviderUnavailable',
} as const satisfies Partial<Record<string, TKey>>;

const proofErrorCodes = new Set([
  'douyin_analysis_required',
  'douyin_proof_invalid',
  'douyin_proof_expired',
  'douyin_proof_mismatch',
]);

function errorText(error: unknown, t: T, context: 'analysis' | 'task', platform: Platform | null): string {
  if (error instanceof ApiError && error.code) {
    if (context === 'task' && proofErrorCodes.has(error.code)) return t('douyinReanalyzeRequired');
    const key = analysisErrorKeys[error.code as keyof typeof analysisErrorKeys];
    if (context === 'analysis' && platform === 'douyin' && key) return t(key);
  }
  return error instanceof Error ? error.message : String(error);
}

export function WorkspacePage({ api, t, settings, state, onState, onTask }: WorkspacePageProps) {
  const {
    url, analysis, selectedFormat, audioFormat, videoOutputFormat, selectedSubtitleLangs,
    mergeSubtitles, saveThumbnail, saveDescription, embedChapters, audioNormalization,
    proxyUrl, concurrentFragments, selectedPlaylistIndexes, mode, accountId,
  } = state;
  const update = (patch: Partial<WorkspaceState>) => onState({ ...state, ...patch });
  const previousMode = useRef(mode);
  const previousAccountPlatform = useRef<Platform | null>(null);
  const initializedAccountPlatforms = useRef(new Set<Platform>());
  const analysisVersion = useRef(0);
  const creatingTask = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const availableFormats = modeFormats(analysis?.formats || [], mode);
  const currentFormat = selectedFormat
    ? availableFormats.find((format) => format.format_id === selectedFormat) || null
    : mode === 'video' ? bestVideoFormat(analysis?.formats || []) : availableFormats.find((format) => format.format_id === 'bestaudio') || availableFormats[0] || null;
  const targetExtractionState = analysis ? rawText(analysis, 'target_extraction_state') : null;
  const canDownload = Boolean(analysis) && !busy && targetExtractionState !== 'unavailable' && !(analysis?.is_playlist && selectedPlaylistIndexes.length === 0);
  const accountPlatform = accountPlatformForUrl(url);
  const platformAccounts = accountPlatform ? accounts.filter((account) => account.platform === accountPlatform) : [];
  const effectiveAccountId = accountPlatform && platformAccounts.some((account) => account.id === accountId && accountCanDownload(account)) ? accountId : null;

  useEffect(() => {
    void api.accounts().then(setAccounts).catch(() => setAccounts([]));
  }, [api]);

  useEffect(() => {
    const platformChanged = previousAccountPlatform.current !== accountPlatform;
    previousAccountPlatform.current = accountPlatform;
    if (!accountPlatform) {
      if (platformChanged) {
        analysisVersion.current += 1;
        update({ accountId: null, analysis: null });
      }
      return;
    }
    if (!accounts.length) {
      if (platformChanged) {
        analysisVersion.current += 1;
        update({ analysis: null });
      }
      return;
    }
    if (!platformChanged && initializedAccountPlatforms.current.has(accountPlatform)) return;
    initializedAccountPlatforms.current.add(accountPlatform);
    const currentAccount = platformAccounts.find((item) => item.id === accountId && accountCanDownload(item));
    const defaultAccount = platformAccounts.find((item) => item.is_default && accountCanDownload(item));
    analysisVersion.current += 1;
    update({ accountId: currentAccount?.id || defaultAccount?.id || null, analysis: null });
  }, [accountPlatform, accounts]);

  async function analyze(accountOverride: string | null = effectiveAccountId) {
    const requestVersion = ++analysisVersion.current;
    const analyzedUrl = url.trim();
    const nextAccountId = accountPlatform ? accountOverride : null;
    update({ analysis: null, accountId: nextAccountId, selectedFormat: null, selectedPlaylistIndexes: [] });
    setBusy(true);
    setError(null);
    try {
      const data = await api.analyze(analyzedUrl, true, nextAccountId);
      if (requestVersion !== analysisVersion.current) return;
      update({
        url: analyzedUrl,
        analysis: data,
        accountId: nextAccountId,
        selectedFormat: preferredFormatForMode(data.formats, mode, settings?.default_video_resolution || 'best'),
        selectedPlaylistIndexes: data.playlist_entries.map((entry) => entry.index),
        selectedSubtitleLangs: [],
      });
    } catch (err) {
      if (requestVersion === analysisVersion.current) setError(errorText(err, t, 'analysis', accountPlatform));
    } finally {
      if (requestVersion === analysisVersion.current) setBusy(false);
    }
  }

  useEffect(() => {
    if (!analysis || previousMode.current === mode) return;
    previousMode.current = mode;
    update({ selectedFormat: preferredFormatForMode(analysis.formats, mode, settings?.default_video_resolution || 'best') });
  }, [mode, analysis, settings?.default_video_resolution]);

  function buildRequest(): CreateTaskRequest {
    return {
      url: analysis ? rawText(analysis, 'resolved_single_video_url') || url : url,
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
      account_id: effectiveAccountId,
      douyin_download_proof: analysis?.douyin_download_proof || null,
      playlist_items: playlistItemsValue(selectedPlaylistIndexes, analysis?.playlist_count),
      playlist_title: analysis?.is_playlist ? rawText(analysis, 'collection_title') || analysis.title || null : null,
      playlist_entries: selectedPlaylistEntries(analysis, selectedPlaylistIndexes),
      filename_template: taskFilenameTemplate(settings?.filename_template || filenameTemplatePresets[2].template, Boolean(analysis?.is_playlist)),
    };
  }

  async function createTask() {
    if (!analysis || creatingTask.current) return;
    creatingTask.current = true;
    setBusy(true);
    setError(null);
    try {
      const task = await api.createTask(buildRequest());
      update({ analysis: null, selectedFormat: null, selectedPlaylistIndexes: [] });
      onTask(task);
    } catch (err) {
      if (err instanceof ApiError && err.code && proofErrorCodes.has(err.code)) {
        update({ analysis: null, selectedFormat: null, selectedPlaylistIndexes: [] });
      }
      setError(errorText(err, t, 'task', accountPlatform));
    } finally {
      creatingTask.current = false;
      setBusy(false);
    }
  }

  async function createMonitor() {
    if (!analysis?.is_playlist) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.createMonitor({ url, interval_minutes: 60, account_id: effectiveAccountId, download_options: buildRequest() });
      if (result.initial_task) onTask(result.initial_task);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function setUrl(value: string) {
    analysisVersion.current += 1;
    update({ url: value, analysis: null, selectedFormat: null, selectedPlaylistIndexes: [] });
    setBusy(false);
    setError(null);
  }

  return <div className={`download-workspace ${analysis ? 'has-analysis' : 'is-empty'}`}>
    <section className="download-intake" aria-label={t('analyzeUrl')}>
      <form className="download-urlbar" onSubmit={(event) => { event.preventDefault(); if (url && !busy) void analyze(); }}>
        <div className="download-url-input"><Download aria-hidden="true" /><input value={url} onChange={(event) => setUrl(event.target.value)} placeholder={t('urlPlaceholder')} autoComplete="off" /></div>
        <button type="button" className="icon-button" onClick={() => navigator.clipboard?.readText().then(setUrl)} title={t('paste')}><ClipboardPaste aria-hidden="true" /></button>
        <button type="submit" className="primary analyze-button" disabled={!url.trim() || busy}>{busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <Sparkles aria-hidden="true" />}{busy ? t('working') : t('analyze')}</button>
      </form>
      {error && <p className="download-error">{error}</p>}
      {!analysis && accountPlatform && !!platformAccounts.length && <label className="workspace-account-select">{t('downloadAccount')}<select value={effectiveAccountId || ''} disabled={busy} onChange={(event) => update({ accountId: event.target.value || null, analysis: null })}><option value="">{t('anonymousAccount')}</option>{platformAccounts.map((account) => <option key={account.id} value={account.id} disabled={!accountCanDownload(account)}>{account.label} · {account.display_name || account.external_id || t('unverifiedAccount')}</option>)}</select></label>}
    </section>

    {!analysis ? <section className="download-empty"><div className="download-empty-mark"><Download aria-hidden="true" /></div><div><h2>{t('downloadEmptyTitle')}</h2><p>{t('analyzeEmpty')}</p></div><div className="download-empty-modes"><span>{t('modeVideo')}</span><span>{t('modeAudio')}</span><span>{t('modeSubtitles')}</span><span>{t('playlist')}</span></div></section> : <div className="download-layout">
      <main className="download-content">
        <AnalysisSummary analysis={analysis} t={t} />
        <AnalysisDetails analysis={analysis} mode={mode} selectedPlaylistIndexes={selectedPlaylistIndexes} selectedFormat={selectedFormat} onPlaylistSelected={(value) => update({ selectedPlaylistIndexes: value })} onFormatSelected={(value) => update({ selectedFormat: value })} t={t} />
      </main>

      <aside className="download-plan">
        <header><div><span>{t('downloadPlan')}</span><h2>{analysis.is_playlist ? t('playlistDownload') : t('singleDownload')}</h2></div>{analysis.is_playlist ? <ListVideo aria-hidden="true" /> : <Download aria-hidden="true" />}</header>
        <div className="download-mode segmented">{(['video', 'audio', 'subtitles'] as DownloadMode[]).map((item) => <button key={item} className={mode === item ? 'active' : ''} onClick={() => update({ mode: item })}>{modeLabel(item, t)}</button>)}</div>

        {accountPlatform && !!platformAccounts.length && <label className="workspace-account-select">{t('downloadAccount')}<select value={effectiveAccountId || ''} disabled={busy} onChange={(event) => void analyze(event.target.value || null)}><option value="">{t('anonymousAccount')}</option>{platformAccounts.map((account) => <option key={account.id} value={account.id} disabled={!accountCanDownload(account)}>{account.label} · {account.display_name || account.external_id || t('unverifiedAccount')}</option>)}</select></label>}

        <div className="plan-section">
          <div className="plan-heading"><span>{t('qualityAndFormat')}</span>{selectedFormat && <span className="badge blue">{t('manualFormatSelection')}</span>}</div>
          <label>{t('formatSelect')}<select value={selectedFormat || ''} onChange={(event) => update({ selectedFormat: event.target.value || null })} disabled={mode === 'subtitles'}><option value="">{mode === 'audio' ? 'bestaudio' : t('autoBestFormat')}</option>{availableFormats.map((format) => <option key={format.format_id} value={format.format_id}>{formatLabel(format)}</option>)}</select></label>
          {mode === 'video' && <label>{t('videoOutputFormat')}<select value={videoOutputFormat} onChange={(event) => update({ videoOutputFormat: event.target.value })}>{['mp4', 'webm', 'mkv'].map((format) => <option key={format} value={format}>{format.toUpperCase()}</option>)}</select></label>}
          {mode === 'audio' && <label>{t('audioOutputFormat')}<select value={audioFormat} onChange={(event) => update({ audioFormat: event.target.value })}>{['mp3', 'm4a', 'opus', 'flac', 'wav'].map((format) => <option key={format} value={format}>{format.toUpperCase()}</option>)}</select></label>}
          {mode !== 'subtitles' && <dl className="download-specs"><div><dt>{t('expectedQuality')}</dt><dd>{mode === 'video' ? qualityLabel(currentFormat?.resolution, t) : t('bestAvailableAudio')}</dd></div><div><dt>{t(mode === 'video' ? 'videoSpecification' : 'audioSpecification')}</dt><dd>{mode === 'video' ? videoSpecification(currentFormat, t) : [friendlyCodec(currentFormat?.audio_codec), currentFormat?.ext?.toUpperCase()].filter(Boolean).join(' · ') || t('formatDetailsUnavailable')}</dd></div>{mode === 'video' && <div><dt>{t('audio')}</dt><dd>{t('bestAvailableAudio')}</dd></div>}</dl>}
        </div>

        {analysis.is_playlist && <div className="playlist-plan-row"><span>{t('selectedVideos')}</span><strong>{selectedPlaylistIndexes.length} / {analysis.playlist_count || analysis.playlist_entries.length}</strong></div>}

        {!!analysis.subtitles.length && <div className="plan-section subtitle-plan"><div className="plan-heading"><span>{t('subtitleLanguages')}</span><span className="badge blue">{selectedSubtitleLangs.length}</span></div><div className="check-grid">{analysis.subtitles.map((subtitle) => <label className="check" key={`${subtitle.language}-${subtitle.automatic ? 'auto' : 'manual'}`}><input type="checkbox" checked={selectedSubtitleLangs.includes(subtitle.language)} onChange={() => update({ selectedSubtitleLangs: toggleListItem(selectedSubtitleLangs, subtitle.language) })} /> {subtitle.language}{subtitle.name ? ` - ${subtitle.name}` : ''}</label>)}</div></div>}

        <div className="download-plan-actions"><button className="primary start-download" onClick={() => void createTask()} disabled={!canDownload}><Download aria-hidden="true" />{busy ? t('working') : t('startDownload')}</button>{analysis.is_playlist && <button onClick={() => void createMonitor()} disabled={!canDownload}><Radar aria-hidden="true" />{t('createMonitor')}</button>}</div>
        <div className="download-destination"><Settings2 aria-hidden="true" /><span>{t('usesSavedDefaults')}</span></div>

        <details className="download-advanced" open={advancedOpen} onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}>
          <summary><span><SlidersHorizontal aria-hidden="true" />{t('advancedOptions')}</span><ChevronDown aria-hidden="true" /></summary>
          <div className="advanced-body">
            <div className="check-grid"><label className="check"><input type="checkbox" checked={mergeSubtitles} onChange={(event) => update({ mergeSubtitles: event.target.checked })} /> {t('mergeSubtitles')}</label><label className="check"><input type="checkbox" checked={saveThumbnail} onChange={(event) => update({ saveThumbnail: event.target.checked })} /> {t('saveThumbnail')}</label><label className="check"><input type="checkbox" checked={saveDescription} onChange={(event) => update({ saveDescription: event.target.checked })} /> {t('saveDescription')}</label><label className="check"><input type="checkbox" checked={embedChapters} onChange={(event) => update({ embedChapters: event.target.checked })} /> {t('embedChapters')}</label><label className="check"><input type="checkbox" checked={audioNormalization} onChange={(event) => update({ audioNormalization: event.target.checked })} disabled={mode !== 'audio'} /> {t('normalizeAudio')}</label></div>
            <label>{t('proxyUrl')}<input value={proxyUrl} placeholder={t('proxyPlaceholder')} onChange={(event) => update({ proxyUrl: event.target.value })} /></label>
            <label>{t('concurrentFragments')}<input type="number" min="1" max="16" value={concurrentFragments} onChange={(event) => update({ concurrentFragments: Math.max(1, Math.min(16, Number(event.target.value) || 1)) })} /></label>
          </div>
        </details>
      </aside>
    </div>}
  </div>;
}
