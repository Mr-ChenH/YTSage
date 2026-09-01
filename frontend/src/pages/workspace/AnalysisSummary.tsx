import { useEffect, useState } from 'react';
import type { AnalyzeResponse } from '../../api/types';
import type { T } from '../../i18n';
import { rawText } from './workspaceUtils';

function warningText(analysis: AnalyzeResponse, t: T): string | null {
  const code = rawText(analysis, 'warning_code') || rawText(analysis, 'warning');
  return code === 'metadata_without_formats' ? t('metadataWithoutFormats') : code;
}

export function AnalysisSummary({ analysis, t }: { analysis: AnalyzeResponse | null; t: T }) {
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  useEffect(() => setThumbnailFailed(false), [analysis?.thumbnail_url]);
  if (!analysis) return <div className="empty-state">{t('analyzeEmpty')}</div>;
  const warning = warningText(analysis, t);
  const webpageUrl = rawText(analysis, 'webpage_url');
  const originalUrl = rawText(analysis, 'original_url');
  const extractor = rawText(analysis, 'extractor') || rawText(analysis, 'extractor_key');
  const thumbnailUrl = analysis.thumbnail_url && !thumbnailFailed ? analysis.thumbnail_url : '/static/assets/main.png';
  return <div className="summary">
    <div className="preview"><img key={thumbnailUrl} src={thumbnailUrl} alt="Video thumbnail" referrerPolicy="no-referrer" onError={() => setThumbnailFailed(true)} /></div>
    <div className="stack">
      <h2>{analysis.title || t('untitled')}</h2>
      <span className="muted">{analysis.channel || t('unknownChannel')} {analysis.duration ? `- ${Math.round(analysis.duration / 60)} ${t('minutes')}` : ''}</span>
      <div className="badge-row"><span className={`badge ${warning ? 'amber' : 'green'}`}>{warning ? t('fallbackFormats') : t('formatsReady')}</span><span className="badge blue">{t('subtitles')}: {analysis.subtitles.length}</span>{analysis.is_playlist && <span className="badge amber">{t('playlist')}: {analysis.playlist_count}</span>}{extractor && <span className="badge">{t('extractor')}: {extractor}</span>}</div>
      {warning && <p className="notice-line"><strong>{t('analyzeWarning')}:</strong> {warning}</p>}
      <div className="meta-grid">{webpageUrl && <a href={webpageUrl} target="_blank" rel="noreferrer"><span>{t('sourcePage')}</span><strong>{webpageUrl}</strong></a>}{originalUrl && originalUrl !== webpageUrl && <a href={originalUrl} target="_blank" rel="noreferrer"><span>{t('originalUrl')}</span><strong>{originalUrl}</strong></a>}</div>
    </div>
  </div>;
}
