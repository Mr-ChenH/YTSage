import { useEffect, useState, type ReactNode } from 'react';
import type { ApiClient } from '../../api/client';
import type { SettingsResponse } from '../../api/types';
import { filenameTemplatePresets, videoResolutionOptions } from '../../config/download';
import type { T, TKey } from '../../i18n';

interface SettingsPageProps {
  api: ApiClient;
  settings: SettingsResponse | null;
  token: string;
  t: T;
  onToken: (value: string) => void;
  onSaved: () => void;
}

function readonlyValue(value: string): ReactNode {
  return <div className="readonly-value">{value || '-'}</div>;
}

function cookieProfileLabel(profile: string, t: T): string {
  const labels: Record<string, TKey> = {
    default: 'cookieProfileDefault',
    bilibili: 'cookieProfileBilibili',
    youtube: 'cookieProfileYoutube',
  };
  return labels[profile] ? t(labels[profile]) : profile;
}

export function SettingsPage({ api, settings, token, t, onToken, onSaved }: SettingsPageProps) {
  const [cookieContent, setCookieContent] = useState('');
  const [cookieProfile, setCookieProfile] = useState('default');
  const [filenameTemplate, setFilenameTemplate] = useState(filenameTemplatePresets[2].template);
  const [defaultVideoResolution, setDefaultVideoResolution] = useState('best');
  const [filenameTemplateStatus, setFilenameTemplateStatus] = useState<string | null>(null);
  const [cookieStatus, setCookieStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (settings?.filename_template) setFilenameTemplate(settings.filename_template);
    if (settings?.default_video_resolution) setDefaultVideoResolution(settings.default_video_resolution);
  }, [settings?.filename_template, settings?.default_video_resolution]);

  async function saveCookies(content: string) {
    setBusy(true);
    setCookieStatus(null);
    try {
      const result = await api.saveCookies(content, cookieProfile);
      setCookieContent('');
      setCookieStatus(`${cookieProfileLabel(result.profile, t)}: ${result.cookies_configured ? t('cookiesSaved') : t('cookiesCleared')}`);
      onSaved();
    } catch (err) {
      setCookieStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function loadCookieFile(file: File | undefined) {
    if (file) setCookieContent(await file.text());
  }

  async function saveFilenameTemplateSetting() {
    setBusy(true);
    setFilenameTemplateStatus(null);
    try {
      await api.saveFilenameTemplate(filenameTemplate, defaultVideoResolution);
      setFilenameTemplateStatus(t('filenameTemplateSaved'));
      onSaved();
    } catch (err) {
      setFilenameTemplateStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return <div className="panel acrylic"><div className="panel-body settings-grid">
    <label>{t('downloadDir')}{readonlyValue(settings?.download_dir || '')}</label>
    <label>{t('configDir')}{readonlyValue(settings?.config_dir || '')}</label>
    <label>{t('filenameTemplatePreset')}<select value={filenameTemplatePresets.some((preset) => preset.template === filenameTemplate) ? filenameTemplate : 'custom'} onChange={(event) => { const preset = filenameTemplatePresets.find((item) => item.template === event.target.value); if (preset) setFilenameTemplate(preset.template); }}>
      {filenameTemplatePresets.map((preset) => <option key={preset.id} value={preset.template}>{preset.template} - {t(preset.descKey)}</option>)}
      <option value="custom">{t('filenameTemplateCustom')} - {t('filenameTemplateDescCustom')}</option>
    </select></label>
    <label className="wide-field">{t('filenameTemplate')}<input value={filenameTemplate} onChange={(event) => setFilenameTemplate(event.target.value)} /></label>
    <label>{t('defaultVideoResolution')}<select value={defaultVideoResolution} onChange={(event) => setDefaultVideoResolution(event.target.value)}>{videoResolutionOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
    <div className="wide-field toolbar"><button className="primary" onClick={() => void saveFilenameTemplateSetting()} disabled={busy || !filenameTemplate.trim()}>{t('saveSettings')}</button>{filenameTemplateStatus && <span className="muted">{filenameTemplateStatus}</span>}</div>
    <label>{t('queueConcurrency')}{readonlyValue(String(settings?.queue_concurrency || 2))}</label>
    <label>{t('authConfigured')}{readonlyValue(settings?.auth_configured ? t('yes') : t('no'))}</label>
    <label>{t('optionalAuthToken')}<input value={token} placeholder={t('notConfigured')} onChange={(event) => onToken(event.target.value)} /></label>
    <label>{t('cookiesConfigured')}{readonlyValue(['default', 'bilibili', 'youtube'].map((profile) => `${cookieProfileLabel(profile, t)}: ${settings?.cookie_profiles?.[profile] ? t('configured') : t('notConfigured')}`).join(' / '))}</label>
    <label>{t('cookieProfile')}<select value={cookieProfile} onChange={(event) => setCookieProfile(event.target.value)}>{['default', 'bilibili', 'youtube'].map((profile) => <option key={profile} value={profile}>{cookieProfileLabel(profile, t)}</option>)}</select></label>
    <label className="wide-field">{t('cookiePaste')}<textarea className="cookie-textarea" value={cookieContent} placeholder={t('cookiePastePlaceholder')} onChange={(event) => setCookieContent(event.target.value)} /></label>
    <div className="wide-field toolbar">
      <label className="file-button"><input type="file" accept=".txt,.cookies" onChange={(event) => void loadCookieFile(event.target.files?.[0])} />{t('uploadCookieFile')}</label>
      <button className="primary" onClick={() => void saveCookies(cookieContent)} disabled={busy || !cookieContent.trim()}>{busy ? t('working') : t('saveCookies')}</button>
      <button onClick={() => void saveCookies('')} disabled={busy || !settings?.cookie_profiles?.[cookieProfile]}>{t('clearCookies')}</button>
      {cookieStatus && <span className="muted">{cookieStatus}</span>}
    </div>
  </div></div>;
}
