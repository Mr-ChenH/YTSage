import { ExternalLink, ListVideo, Radio, Subtitles } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { AnalyzeResponse } from '../../api/types';
import type { T } from '../../i18n';
import { rawText } from './workspaceUtils';

function warningText(analysis: AnalyzeResponse, t: T): string | null {
  const code = rawText(analysis, 'warning_code') || rawText(analysis, 'warning');
  if (code !== 'metadata_without_formats') return code;
  return t(rawText(analysis, 'target_extraction_state') === 'unavailable' ? 'metadataWithoutFormatsUnavailable' : 'metadataWithoutFormats');
}

function cookieAnalysisStatus(analysis: AnalyzeResponse, field: string, t: T): { text: string; error: boolean } | null {
  const status = rawText(analysis, field);
  if (!status) return null;
  const labels: Record<string, Parameters<T>[0]> = field === 'cookie_login_status'
    ? { valid: 'cookieLoginValid', invalid: 'cookieLoginInvalid', unknown: 'cookieLoginUnknown' }
    : { valid: 'cookieExpiryValid', session: 'cookieSession', expiring: 'cookieExpiring', expired: 'cookieExpired', invalid: 'cookieInvalid' };
  const key = labels[status];
  return key ? { text: t(key), error: status === 'invalid' || status === 'expired' } : null;
}

function accountProbeStatus(analysis: AnalyzeResponse, field: 'account_identity_state' | 'target_extraction_state', t: T): { text: string; tone: 'green' | 'amber' | 'red' } | null {
  const value = rawText(analysis, field);
  if (!value) return null;
  const labels: Record<string, Parameters<T>[0]> = field === 'account_identity_state'
    ? { valid: 'accountIdentityValid', unknown: 'accountIdentityUnknown', invalid: 'accountIdentityInvalid', expired: 'accountIdentityInvalid' }
    : { valid: 'targetExtractionValid', unavailable: 'targetExtractionUnavailable', not_probed: 'targetExtractionNotProbed' };
  const key = labels[value];
  if (!key) return null;
  return {
    text: t(key),
    tone: value === 'valid' ? 'green' : value === 'invalid' || value === 'expired' || value === 'unavailable' ? 'red' : 'amber',
  };
}

export function AnalysisSummary({ analysis, t }: { analysis: AnalyzeResponse | null; t: T }) {
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  useEffect(() => setThumbnailFailed(false), [analysis?.thumbnail_url]);
  if (!analysis) return null;
  const warning = warningText(analysis, t);
  const cookieExpiry = cookieAnalysisStatus(analysis, 'cookie_expiry_status', t);
  const accountIdentity = accountProbeStatus(analysis, 'account_identity_state', t);
  const targetExtraction = accountProbeStatus(analysis, 'target_extraction_state', t);
  const cookieLogin = accountIdentity ? null : cookieAnalysisStatus(analysis, 'cookie_login_status', t);
  const webpageUrl = rawText(analysis, 'webpage_url');
  const originalUrl = rawText(analysis, 'original_url');
  const sourceUrl = webpageUrl || originalUrl;
  const extractor = rawText(analysis, 'extractor') || rawText(analysis, 'extractor_key');
  const thumbnailUrl = analysis.thumbnail_url && !thumbnailFailed ? analysis.thumbnail_url : `${import.meta.env.BASE_URL}assets/main.png`;
  return <section className="media-summary">
    <div className="media-preview"><img key={thumbnailUrl} src={thumbnailUrl} alt="" referrerPolicy="no-referrer" onError={() => setThumbnailFailed(true)} /></div>
    <div className="media-summary-copy">
      <div className="media-title-row"><div><span>{analysis.is_playlist ? t('playlist') : t('mediaReady')}</span><h2>{analysis.title || t('untitled')}</h2></div>{sourceUrl && <a className="icon-button" href={sourceUrl} target="_blank" rel="noreferrer" title={t('sourcePage')}><ExternalLink aria-hidden="true" /></a>}</div>
      <p>{analysis.channel || t('unknownChannel')}{analysis.duration ? ` · ${Math.round(analysis.duration / 60)} ${t('minutes')}` : ''}{extractor ? ` · ${extractor}` : ''}</p>
      <div className="media-stats"><span><Radio aria-hidden="true" />{analysis.formats.length} {t('formatsCount')}</span><span><Subtitles aria-hidden="true" />{analysis.subtitles.length} {t('subtitles')}</span>{analysis.is_playlist && <span><ListVideo aria-hidden="true" />{analysis.playlist_count} {t('playlistItems')}</span>}</div>
      <div className="badge-row">{targetExtraction?.tone !== 'red' && <span className={`badge ${warning ? 'amber' : 'green'}`}>{warning ? t('fallbackFormats') : t('formatsReady')}</span>}{cookieExpiry && <span className={`badge ${cookieExpiry.error ? 'red' : 'green'}`}>{cookieExpiry.text}</span>}{accountIdentity && <span className={`badge ${accountIdentity.tone}`}>{accountIdentity.text}</span>}{targetExtraction && <span className={`badge ${targetExtraction.tone}`}>{targetExtraction.text}</span>}{cookieLogin && <span className={`badge ${cookieLogin.error ? 'red' : cookieLogin.text === t('cookieLoginUnknown') ? 'amber' : 'green'}`}>{cookieLogin.text}</span>}</div>
    </div>
    {warning && <p className="notice-line"><strong>{t('analyzeWarning')}:</strong> {warning}</p>}
  </section>;
}
