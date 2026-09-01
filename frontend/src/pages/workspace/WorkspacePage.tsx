import { useEffect, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { AnalyzeResponse, CreateTaskRequest, DownloadMode, SettingsResponse, TaskResponse } from '../../api/types';
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

interface WorkspacePageProps {
  api: ApiClient;
  t: T;
  settings: SettingsResponse | null;
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

export function WorkspacePage({ api, t, settings, onTask }: WorkspacePageProps) {
  const [url, setUrl] = useState('');
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [selectedFormat, setSelectedFormat] = useState<string | null>(null);
  const [audioFormat, setAudioFormat] = useState('mp3');
  const [videoOutputFormat, setVideoOutputFormat] = useState('mp4');
  const [selectedSubtitleLangs, setSelectedSubtitleLangs] = useState<string[]>([]);
  const [mergeSubtitles, setMergeSubtitles] = useState(true);
  const [saveThumbnail, setSaveThumbnail] = useState(false);
  const [saveDescription, setSaveDescription] = useState(false);
  const [embedChapters, setEmbedChapters] = useState(true);
  const [audioNormalization, setAudioNormalization] = useState(false);
  const [proxyUrl, setProxyUrl] = useState('');
  const [concurrentFragments, setConcurrentFragments] = useState(4);
  const [selectedPlaylistIndexes, setSelectedPlaylistIndexes] = useState<number[]>([]);
  const [mode, setMode] = useState<DownloadMode>('video');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function analyze() {
    setBusy(true);
    setError(null);
    try {
      const data = await api.analyze(url);
      setAnalysis(data);
      setSelectedFormat(preferredFormatForMode(data.formats, mode, settings?.default_video_resolution || 'best'));
      setSelectedPlaylistIndexes(data.playlist_entries.map((entry) => entry.index));
      setSelectedSubtitleLangs([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (analysis) setSelectedFormat(preferredFormatForMode(analysis.formats, mode, settings?.default_video_resolution || 'best'));
  }, [mode, analysis, settings?.default_video_resolution]);

  async function createTask() {
    setBusy(true);
    setError(null);
    const request: CreateTaskRequest = {
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
    try {
      onTask(await api.createTask(request));
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
        <div className="urlbar"><input value={url} onChange={(event) => setUrl(event.target.value)} placeholder={t('urlPlaceholder')} /><button onClick={() => navigator.clipboard?.readText().then(setUrl)}>{t('paste')}</button><button className="primary" onClick={analyze} disabled={!url || busy}>{busy ? t('working') : t('analyze')}</button></div>
        {error && <p className="error-line">{error}</p>}
        <AnalysisSummary analysis={analysis} t={t} />
        <AnalysisDetails analysis={analysis} mode={mode} selectedPlaylistIndexes={selectedPlaylistIndexes} selectedFormat={selectedFormat} onPlaylistSelected={setSelectedPlaylistIndexes} onFormatSelected={setSelectedFormat} t={t} />
      </div>
    </div>
    <aside className="panel acrylic">
      <div className="panel-header"><h2>{t('downloadOptions')}</h2><span className="badge">{t('queued')}</span></div>
      <div className="panel-body options-grid">
        <div className="segmented">{(['video', 'audio', 'subtitles'] as DownloadMode[]).map((item) => <button key={item} className={mode === item ? 'active' : ''} onClick={() => setMode(item)}>{modeLabel(item, t)}</button>)}</div>
        <label>{t('formatSelect')}<select value={selectedFormat || ''} onChange={(event) => setSelectedFormat(event.target.value || null)} disabled={mode === 'subtitles'}><option value="">{mode === 'audio' ? 'bestaudio' : t('autoBestFormat')}</option>{modeFormats(analysis?.formats || [], mode).map((format) => <option key={format.format_id} value={format.format_id}>{formatLabel(format)}</option>)}</select></label>
        {mode === 'video' && <label>{t('videoOutputFormat')}<select value={videoOutputFormat} onChange={(event) => setVideoOutputFormat(event.target.value)}>{['mp4', 'webm', 'mkv'].map((format) => <option key={format} value={format}>{format}</option>)}</select></label>}
        {mode === 'audio' && <label>{t('audioOutputFormat')}<select value={audioFormat} onChange={(event) => setAudioFormat(event.target.value)}>{['mp3', 'm4a', 'opus', 'flac', 'wav'].map((format) => <option key={format} value={format}>{format}</option>)}</select></label>}
        {!!analysis?.subtitles.length && <div className="section-block compact-options"><div className="section-heading"><h3>{t('subtitleLanguages')}</h3><span className="badge blue">{selectedSubtitleLangs.length}</span></div><div className="check-grid">{analysis.subtitles.map((subtitle) => <label className="check" key={`${subtitle.language}-${subtitle.automatic ? 'auto' : 'manual'}`}><input type="checkbox" checked={selectedSubtitleLangs.includes(subtitle.language)} onChange={() => setSelectedSubtitleLangs((current) => toggleListItem(current, subtitle.language))} /> {subtitle.language}{subtitle.name ? ` - ${subtitle.name}` : ''}</label>)}</div></div>}
        <div className="check-grid"><label className="check"><input type="checkbox" checked={mergeSubtitles} onChange={(event) => setMergeSubtitles(event.target.checked)} /> {t('mergeSubtitles')}</label><label className="check"><input type="checkbox" checked={saveThumbnail} onChange={(event) => setSaveThumbnail(event.target.checked)} /> {t('saveThumbnail')}</label><label className="check"><input type="checkbox" checked={saveDescription} onChange={(event) => setSaveDescription(event.target.checked)} /> {t('saveDescription')}</label><label className="check"><input type="checkbox" checked={embedChapters} onChange={(event) => setEmbedChapters(event.target.checked)} /> {t('embedChapters')}</label><label className="check"><input type="checkbox" checked={audioNormalization} onChange={(event) => setAudioNormalization(event.target.checked)} disabled={mode !== 'audio'} /> {t('normalizeAudio')}</label></div>
        <label>{t('proxyUrl')}<input value={proxyUrl} placeholder={t('proxyPlaceholder')} onChange={(event) => setProxyUrl(event.target.value)} /></label>
        <label>{t('concurrentFragments')}<input type="number" min="1" max="16" value={concurrentFragments} onChange={(event) => setConcurrentFragments(Math.max(1, Math.min(16, Number(event.target.value) || 1)))} /></label>
        <button className="primary" onClick={createTask} disabled={!url || busy || Boolean(analysis?.is_playlist && selectedPlaylistIndexes.length === 0)}>{t('createTask')}</button>
      </div>
    </aside>
  </div>;
}
