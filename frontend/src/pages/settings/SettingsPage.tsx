import { AlertCircle, CheckCircle2, Download, FileKey2, Folder, Save, ShieldCheck, Trash2, Upload } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { CookieProfileStatus, SettingsResponse } from '../../api/types';
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

type SettingsSection = 'downloads' | 'credentials' | 'access';
const cookieProfiles = ['default', 'bilibili', 'youtube'] as const;

function cookieProfileLabel(profile: string, t: T): string {
  const labels: Record<string, TKey> = { default: 'cookieProfileDefault', bilibili: 'cookieProfileBilibili', youtube: 'cookieProfileYoutube' };
  return labels[profile] ? t(labels[profile]) : profile;
}

function cookieExpiryLabel(status: CookieProfileStatus | undefined, t: T): string {
  if (!status) return t('notConfigured');
  const labels: Record<CookieProfileStatus['state'], TKey> = {
    not_configured: 'notConfigured', valid: 'cookieValid', session: 'cookieSession', expiring: 'cookieExpiring', expired: 'cookieExpired', invalid: 'cookieInvalid',
  };
  return t(labels[status.state]);
}

function cookieLoginLabel(status: CookieProfileStatus | undefined, t: T): string {
  if (!status?.configured || !status.login_state) return t('cookieLoginNotChecked');
  const state = t({ valid: 'cookieLoginValid', invalid: 'cookieLoginInvalid', unknown: 'cookieLoginUnknown' }[status.login_state] as TKey);
  return status.login_checked_at ? `${state} · ${new Date(status.login_checked_at * 1000).toLocaleString()}` : state;
}

function cookieTone(status: CookieProfileStatus | undefined): string {
  if (!status?.configured) return '';
  if (!status.usable || status.login_state === 'invalid') return 'error';
  if (status.state === 'expiring' || status.login_state === 'unknown') return 'warning';
  return 'valid';
}

export function SettingsPage({ api, settings, token, t, onToken, onSaved }: SettingsPageProps) {
  const [section, setSection] = useState<SettingsSection>('downloads');
  const [cookieContent, setCookieContent] = useState('');
  const [cookieProfile, setCookieProfile] = useState<(typeof cookieProfiles)[number]>('default');
  const [filenameTemplate, setFilenameTemplate] = useState(filenameTemplatePresets[2].template);
  const [defaultVideoResolution, setDefaultVideoResolution] = useState('best');
  const [filenameTemplateStatus, setFilenameTemplateStatus] = useState<string | null>(null);
  const [cookieStatusMessage, setCookieStatusMessage] = useState<string | null>(null);
  const [templateBusy, setTemplateBusy] = useState(false);
  const [cookieBusy, setCookieBusy] = useState(false);

  useEffect(() => {
    if (settings?.filename_template) setFilenameTemplate(settings.filename_template);
    if (settings?.default_video_resolution) setDefaultVideoResolution(settings.default_video_resolution);
  }, [settings?.filename_template, settings?.default_video_resolution]);

  const selectedCookieStatus = settings?.cookie_profile_status?.[cookieProfile];
  const templatePreset = filenameTemplatePresets.find((preset) => preset.template === filenameTemplate);
  const templateChanged = Boolean(settings && (filenameTemplate !== settings.filename_template || defaultVideoResolution !== settings.default_video_resolution));
  const usableCookieCount = useMemo(() => cookieProfiles.filter((profile) => settings?.cookie_profile_status?.[profile]?.usable).length, [settings]);

  async function saveCookies(content: string) {
    setCookieBusy(true);
    setCookieStatusMessage(null);
    try {
      const result = await api.saveCookies(content, cookieProfile);
      setCookieContent('');
      setCookieStatusMessage(result.cookies_configured ? t('cookiesSaved') : t('cookiesCleared'));
      onSaved();
    } catch (err) {
      setCookieStatusMessage(err instanceof Error ? err.message : String(err));
    } finally {
      setCookieBusy(false);
    }
  }

  async function loadCookieFile(file: File | undefined) {
    if (file) setCookieContent(await file.text());
  }

  async function saveFilenameTemplateSetting() {
    setTemplateBusy(true);
    setFilenameTemplateStatus(null);
    try {
      await api.saveFilenameTemplate(filenameTemplate, defaultVideoResolution);
      setFilenameTemplateStatus(t('filenameTemplateSaved'));
      onSaved();
    } catch (err) {
      setFilenameTemplateStatus(err instanceof Error ? err.message : String(err));
    } finally {
      setTemplateBusy(false);
    }
  }

  if (!settings) return <div className="empty-state">{t('working')}</div>;
  const sections: Array<{ id: SettingsSection; icon: typeof Download; title: TKey; description: TKey; meta: string }> = [
    { id: 'downloads', icon: Download, title: 'settingsDownloads', description: 'settingsDownloadsNavDesc', meta: defaultVideoResolution === 'best' ? t('autoBestFormat') : defaultVideoResolution },
    { id: 'credentials', icon: FileKey2, title: 'settingsCredentials', description: 'settingsCredentialsNavDesc', meta: `${usableCookieCount} / ${cookieProfiles.length}` },
    { id: 'access', icon: ShieldCheck, title: 'settingsAccess', description: 'settingsAccessNavDesc', meta: settings.auth_configured ? t('enabled') : t('disabled') },
  ];

  return <div className="settings-console">
    <nav className="settings-nav" aria-label={t('settingsCategories')}>{sections.map(({ id, icon: Icon, title, description, meta }) => <button key={id} className={section === id ? 'active' : ''} onClick={() => setSection(id)} aria-current={section === id ? 'page' : undefined}><span className="settings-nav-icon"><Icon aria-hidden="true" /></span><span><strong>{t(title)}</strong><small>{t(description)}</small></span><span className="settings-nav-meta">{meta}</span></button>)}</nav>

    <div className="settings-content">
      {section === 'downloads' && <section className="settings-pane">
        <header><div><h2>{t('downloadDefaults')}</h2><p>{t('downloadDefaultsDesc')}</p></div>{filenameTemplateStatus && <span className="settings-feedback"><CheckCircle2 aria-hidden="true" />{filenameTemplateStatus}</span>}</header>
        <div className="settings-form">
          <div className="settings-subsection"><div className="settings-subsection-heading"><h3>{t('qualityAndNaming')}</h3><span>{t('qualityAndNamingDesc')}</span></div><div className="download-settings-grid">
            <label>{t('defaultVideoResolution')}<select value={defaultVideoResolution} onChange={(event) => setDefaultVideoResolution(event.target.value)}>{videoResolutionOptions.map((item) => <option key={item} value={item}>{item === 'best' ? t('autoBestFormat') : item}</option>)}</select><small>{t('defaultVideoResolutionHint')}</small></label>
            <label>{t('filenameTemplatePreset')}<select value={templatePreset?.template || 'custom'} onChange={(event) => { const preset = filenameTemplatePresets.find((item) => item.template === event.target.value); if (preset) setFilenameTemplate(preset.template); }}>{filenameTemplatePresets.map((preset) => <option key={preset.id} value={preset.template}>{t(preset.descKey)}</option>)}<option value="custom">{t('filenameTemplateCustom')}</option></select><small>{templatePreset ? t(templatePreset.descKey) : t('filenameTemplateDescCustom')}</small></label>
            <label className="settings-wide">{t('filenameTemplate')}<input value={filenameTemplate} onChange={(event) => setFilenameTemplate(event.target.value)} /><small>{t('filenameTemplateVariablesHint')}</small></label>
          </div></div>
          <div className="settings-subsection"><div className="settings-subsection-heading"><h3>{t('storageLocations')}</h3><span>{t('storageLocationsDesc')}</span></div><div className="settings-location-list"><div><Folder aria-hidden="true" /><span><small>{t('downloadDir')}</small><strong title={settings.download_dir}>{settings.download_dir}</strong></span></div><div><Folder aria-hidden="true" /><span><small>{t('configDir')}</small><strong title={settings.config_dir}>{settings.config_dir}</strong></span></div></div></div>
        </div>
        <footer><button className={templateChanged || templateBusy ? 'primary' : ''} onClick={() => void saveFilenameTemplateSetting()} disabled={templateBusy || !filenameTemplate.trim() || !templateChanged}><Save aria-hidden="true" />{templateBusy ? t('working') : t('saveChanges')}</button></footer>
      </section>}

      {section === 'credentials' && <section className="settings-pane">
        <header><div><h2>{t('cookieAndLogin')}</h2><p>{t('cookieAndLoginDesc')}</p></div><span className="badge">{t('usableProfiles')}: {usableCookieCount} / {cookieProfiles.length}</span></header>
        <div className="settings-form credential-form">
          <div className="cookie-profile-tabs" role="tablist" aria-label={t('cookieProfile')}>{cookieProfiles.map((profile) => { const status = settings.cookie_profile_status?.[profile]; const tone = cookieTone(status); return <button key={profile} className={cookieProfile === profile ? 'active' : ''} onClick={() => { setCookieProfile(profile); setCookieStatusMessage(null); }} role="tab" aria-selected={cookieProfile === profile}><span className={`cookie-profile-dot ${tone}`} /><span><strong>{cookieProfileLabel(profile, t)}</strong><small>{cookieExpiryLabel(status, t)}</small></span></button>; })}</div>
          <div className="cookie-status-grid"><div><span>{t('cookieExpiryStatus')}</span><strong>{cookieExpiryLabel(selectedCookieStatus, t)}</strong></div><div><span>{t('cookieLoginStatus')}</span><strong title={cookieLoginLabel(selectedCookieStatus, t)}>{cookieLoginLabel(selectedCookieStatus, t)}</strong></div><div><span>{t('validCookies')}</span><strong>{selectedCookieStatus?.valid_count || 0} / {selectedCookieStatus?.total_count || 0}</strong></div><div><span>{t('cookieEarliestExpiry')}</span><strong>{selectedCookieStatus?.earliest_expiry ? new Date(selectedCookieStatus.earliest_expiry * 1000).toLocaleString() : '-'}</strong></div></div>
          <label className="cookie-input-field"><span>{t('replaceCookieData')}</span><textarea className="cookie-textarea" value={cookieContent} placeholder={t('cookiePastePlaceholder')} onChange={(event) => setCookieContent(event.target.value)} /><small>{t('cookieReplaceHint')}</small></label>
        </div>
        <footer className="settings-actions"><label className="file-button"><input type="file" accept=".txt,.cookies,.json" onChange={(event) => void loadCookieFile(event.target.files?.[0])} /><Upload aria-hidden="true" />{t('chooseCookieFile')}</label><button className={cookieContent.trim() || cookieBusy ? 'primary' : ''} onClick={() => void saveCookies(cookieContent)} disabled={cookieBusy || !cookieContent.trim()}><Save aria-hidden="true" />{cookieBusy ? t('working') : t('replaceCookies')}</button><button className="danger" onClick={() => void saveCookies('')} disabled={cookieBusy || !selectedCookieStatus?.configured}><Trash2 aria-hidden="true" />{t('clearCookies')}</button>{cookieStatusMessage && <span className="settings-feedback">{cookieStatusMessage}</span>}</footer>
      </section>}

      {section === 'access' && <section className="settings-pane">
        <header><div><h2>{t('accessToken')}</h2><p>{t('accessTokenDesc')}</p></div><span className={`badge ${settings.auth_configured ? 'green' : ''}`}>{settings.auth_configured ? t('serverRequiresToken') : t('serverNoTokenRequired')}</span></header>
        <div className="settings-form access-form"><div className={`access-status ${settings.auth_configured ? 'required' : ''}`}><ShieldCheck aria-hidden="true" /><div><strong>{settings.auth_configured ? t('authenticationRequired') : t('authenticationNotRequired')}</strong><span>{settings.auth_configured ? t('authenticationRequiredDesc') : t('authenticationNotRequiredDesc')}</span></div></div><label>{t('optionalAuthToken')}<input type="password" value={token} placeholder={t('notConfigured')} onChange={(event) => onToken(event.target.value)} autoComplete="off" /><small>{t('tokenStoredLocally')}</small></label></div>
      </section>}
    </div>
  </div>;
}
