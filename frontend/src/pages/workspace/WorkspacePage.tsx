import { useEffect, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { CreateTaskRequest, DownloadMode, SettingsResponse, TaskResponse } from '../../api/types';
import { filenameTemplatePresets } from '../../config/download';
import type { T, TKey } from '../../i18n';
import { AnalysisDetails } from './AnalysisDetails';
import { AnalysisSummary } from './AnalysisSummary';
import {
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
  const labels: Record<DownloadMode, TKey> = {
    video: 'modeVideo',
    audio: 'modeAudio',
    subtitles: 'modeSubtitles',
  };
  return t(labels[mode]);
}

export function WorkspacePage({ api, t, settings, state, onState, onTask }: WorkspacePageProps) {
  const {
    url, analysis, selectedFormat, audioFormat, videoOutputFormat, selectedSubtitleLangs,
    mergeSubtitles, saveThumbnail, saveDescription, embedChapters, audioNormalization,
    proxyUrl, concurrentFragments, selectedPlaylistIndexes, mode,
  } = state;
  const update = (patch: Partial<WorkspaceState>) => onState({ ...state, ...patch });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function analyze() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.analyze(url);
      update({
        analysis: data,
        selectedFormat: preferredFormatForMode(data.formats, mode, settings?.default_video_resolution || 'best'),
        selectedPlaylistIndexes: data.playlist_entries.map((entry) => entry.index),
        selectedSubtitleLangs: [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (analysis) update({ selectedFormat: preferredFormatForMode(analysis.formats, mode, settings?.default_video_resolution || 'best') });
  }, [mode, analysis, settings?.default_video_resolution]);

  function buildRequest(): CreateTaskRequest {
    return {
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
  }

  async function createTask() {
    setBusy(true);
    setError(null);
    try {
      onTask(await api.createTask(buildRequest()));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function createMonitor() {
    if (!analysis?.is_playlist) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.createMonitor({ url, interval_minutes: 60, download_options: buildRequest() });
      onTask(result.initial_task);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return <div className="workspace-grid">
    <div className="panel acrylic">
      <div className="panel-header"><h2>{t('analyzeUrl')}</h2>{analysis && <span className="badge blue">{analysis.formats.length} {t('formatsCount')}</span>}</div>
      <div className="panel-body">
        <div className="urlbar"><input value={url} onChange={(event) => update({ url: event.target.value, analysis: null, selectedFormat: null, selectedPlaylistIndexes: [] })} placeholder={t('urlPlaceholder')} /><button onClick={() => navigator.clipboard?.readText().then((value) => update({ url: value, analysis: null, selectedFormat: null, selectedPlaylistIndexes: [] }))}>{t('paste')}</button><button className="primary" onClick={analyze} disabled={!url || busy}>{busy ? t('working') : t('analyze')}</button></div>
        {error && <p className="error-line">{error}</p>}
        <AnalysisSummary analysis={analysis} t={t} />
        <AnalysisDetails analysis={analysis} mode={mode} selectedPlaylistIndexes={selectedPlaylistIndexes} selectedFormat={selectedFormat} onPlaylistSelected={(value) => update({ selectedPlaylistIndexes: value })} onFormatSelected={(value) => update({ selectedFormat: value })} t={t} />
      </div>
    </div>
    <aside className="panel acrylic">
      <div className="panel-header"><h2>{t('downloadOptions')}</h2><span className="badge">{t('queued')}</span></div>
      <div className="panel-body options-grid">
        <div className="segmented">{(['video', 'audio', 'subtitles'] as DownloadMode[]).map((item) => <button key={item} className={mode === item ? 'active' : ''} onClick={() => update({ mode: item })}>{modeLabel(item, t)}</button>)}</div>
        <label>{t('formatSelect')}<select value={selectedFormat || ''} onChange={(event) => update({ selectedFormat: event.target.value || null })} disabled={mode === 'subtitles'}><option value="">{mode === 'audio' ? 'bestaudio' : t('autoBestFormat')}</option>{modeFormats(analysis?.formats || [], mode).map((format) => <option key={format.format_id} value={format.format_id}>{formatLabel(format)}</option>)}</select></label>
        {mode === 'video' && <label>{t('videoOutputFormat')}<select value={videoOutputFormat} onChange={(event) => update({ videoOutputFormat: event.target.value })}>{['mp4', 'webm', 'mkv'].map((format) => <option key={format} value={format}>{format}</option>)}</select></label>}
        {mode === 'audio' && <label>{t('audioOutputFormat')}<select value={audioFormat} onChange={(event) => update({ audioFormat: event.target.value })}>{['mp3', 'm4a', 'opus', 'flac', 'wav'].map((format) => <option key={format} value={format}>{format}</option>)}</select></label>}
        {!!analysis?.subtitles.length && <div className="section-block compact-options"><div className="section-heading"><h3>{t('subtitleLanguages')}</h3><span className="badge blue">{selectedSubtitleLangs.length}</span></div><div className="check-grid">{analysis.subtitles.map((subtitle) => <label className="check" key={`${subtitle.language}-${subtitle.automatic ? 'auto' : 'manual'}`}><input type="checkbox" checked={selectedSubtitleLangs.includes(subtitle.language)} onChange={() => update({ selectedSubtitleLangs: toggleListItem(selectedSubtitleLangs, subtitle.language) })} /> {subtitle.language}{subtitle.name ? ` - ${subtitle.name}` : ''}</label>)}</div></div>}
        <div className="check-grid"><label className="check"><input type="checkbox" checked={mergeSubtitles} onChange={(event) => update({ mergeSubtitles: event.target.checked })} /> {t('mergeSubtitles')}</label><label className="check"><input type="checkbox" checked={saveThumbnail} onChange={(event) => update({ saveThumbnail: event.target.checked })} /> {t('saveThumbnail')}</label><label className="check"><input type="checkbox" checked={saveDescription} onChange={(event) => update({ saveDescription: event.target.checked })} /> {t('saveDescription')}</label><label className="check"><input type="checkbox" checked={embedChapters} onChange={(event) => update({ embedChapters: event.target.checked })} /> {t('embedChapters')}</label><label className="check"><input type="checkbox" checked={audioNormalization} onChange={(event) => update({ audioNormalization: event.target.checked })} disabled={mode !== 'audio'} /> {t('normalizeAudio')}</label></div>
        <label>{t('proxyUrl')}<input value={proxyUrl} placeholder={t('proxyPlaceholder')} onChange={(event) => update({ proxyUrl: event.target.value })} /></label>
        <label>{t('concurrentFragments')}<input type="number" min="1" max="16" value={concurrentFragments} onChange={(event) => update({ concurrentFragments: Math.max(1, Math.min(16, Number(event.target.value) || 1)) })} /></label>
        <div className="toolbar"><button className="primary" onClick={createTask} disabled={!url || busy || Boolean(analysis?.is_playlist && selectedPlaylistIndexes.length === 0)}>{t('createTask')}</button><button onClick={createMonitor} disabled={!analysis?.is_playlist || busy}>{t('createMonitor')}</button></div>
      </div>
    </aside>
  </div>;
}
