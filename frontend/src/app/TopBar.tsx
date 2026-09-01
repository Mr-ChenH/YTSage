import { CircleUserRound, Languages, RefreshCw } from 'lucide-react';
import type { HealthResponse } from '../api/types';
import type { Locale, T, TKey } from '../i18n';
import type { Page } from './navigation';

interface TopBarProps {
  page: Page;
  health: HealthResponse | null;
  authRequired: boolean;
  token: string;
  locale: Locale;
  t: T;
  onLocale: (value: Locale) => void;
  onToken: (value: string) => void;
  onRefresh: () => void;
  error: string | null;
}

const titles: Record<Page, [TKey, TKey]> = {
  workspace: ['workspaceTitle', 'workspaceDesc'],
  tasks: ['tasksTitle', 'tasksDesc'],
  history: ['historyTitle', 'historyDesc'],
  files: ['filesTitle', 'filesDesc'],
  player: ['playerTitle', 'playerDesc'],
  settings: ['settingsTitle', 'settingsDesc'],
  system: ['systemTitle', 'systemDesc'],
};

export function TopBar({ page, health, authRequired, token, locale, t, onLocale, onToken, onRefresh, error }: TopBarProps) {
  return (
    <header className="topbar glass-toolbar">
      <div className="page-heading">
        <span className="page-kicker">YTSage</span>
        <h1>{t(titles[page][0])}</h1>
        <p className="muted">{t(titles[page][1])}</p>
        {error && <p className="error-line">{error}</p>}
      </div>
      <div className="topbar-controls">
        {(authRequired || token) && <div className="toolbar-group auth-control"><CircleUserRound size={16} aria-hidden="true" /><input className="token-input" value={token} placeholder={t('bearerToken')} onChange={(event) => onToken(event.target.value)} /></div>}
        <div className="toolbar-group">
          <span className="health-indicator" title={health?.healthy ? t('healthy') : t('needsTools')}><span className={`dot ${health?.healthy ? '' : 'amber'}`} />{health?.healthy ? t('healthy') : t('needsTools')}</span>
          <label className="language-label" title={t('language')}>
            <Languages size={15} aria-hidden="true" />
            <select className="language-select" value={locale} onChange={(event) => onLocale(event.target.value as Locale)} aria-label={t('language')}>
              <option value="zh">{t('chinese')}</option>
              <option value="en">{t('english')}</option>
            </select>
          </label>
        </div>
        <button className="icon-button toolbar-refresh" onClick={onRefresh} title={t('refresh')} aria-label={t('refresh')}><RefreshCw size={17} /></button>
      </div>
    </header>
  );
}
