import { AlertTriangle, CheckCircle2, ChevronLeft, Download, ExternalLink, FolderHeart, KeyRound, LoaderCircle, Pencil, Plus, QrCode, Radar, RefreshCw, ShieldCheck, Sparkles, Star, Trash2, Upload, UserRound } from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { useEffect, useRef, useState } from 'react';
import { ApiError, type ApiClient } from '../../api/client';
import type { AccountResource, AccountResourceEntriesResponse, AccountResourceType, HealthResponse, Platform, PlatformAccount, TaskResponse } from '../../api/types';
import type { T, TKey } from '../../i18n';
import { formatDuration } from '../../shared/format';

interface AccountsPageProps {
  api: ApiClient;
  health: HealthResponse | null;
  t: T;
  onAnalyze: (url: string, accountId: string) => void;
  onTask: (task: TaskResponse) => void;
}

type BilibiliResourceKind = Extract<AccountResourceType, 'created_favorite' | 'collected_favorite' | 'collection' | 'watch_later'>;
type DouyinResourceKind = Extract<AccountResourceType, 'douyin_works' | 'douyin_favorites' | 'douyin_collections'>;
type ResourceKind = BilibiliResourceKind | DouyinResourceKind;
const bilibiliResourceKinds: BilibiliResourceKind[] = ['created_favorite', 'collected_favorite', 'collection', 'watch_later'];
const douyinResourceKinds: DouyinResourceKind[] = ['douyin_works', 'douyin_favorites', 'douyin_collections'];
const bilibiliPageSize = 20;
const douyinPageSize = 10;

function pageSizeForPlatform(platform: Platform): number {
  return platform === 'douyin' ? douyinPageSize : bilibiliPageSize;
}

function stateClass(account: PlatformAccount): string {
  return account.state === 'valid' ? 'valid' : account.state === 'unknown' ? 'warning' : 'error';
}

function accountStateKey(account: PlatformAccount): TKey {
  if (account.state === 'valid') return 'accountValid';
  if (account.state === 'unknown') return 'accountUnknown';
  if (account.state === 'expired') return 'accountExpired';
  return 'accountInvalid';
}

function platformName(platform: Platform, t: T): string {
  return t(platform === 'bilibili' ? 'platformBilibili' : 'platformDouyin');
}

function isEntryDownloadable(entry: AccountResourceEntriesResponse['entries'][number]): boolean {
  return entry.is_available !== false && Boolean(entry.id && entry.url);
}

function canonicalEntryUrl(entry: AccountResourceEntriesResponse['entries'][number]): string | null {
  return entry.webpage_url || entry.url || null;
}

const douyinResourceErrorKeys = {
  provider_risk_control: 'douyinResourceRiskControl',
  provider_timeout: 'douyinResourceTimeout',
  provider_unavailable: 'douyinResourceUnavailable',
  provider_response_invalid: 'douyinResourceInvalidResponse',
  account_login_invalid: 'douyinResourceLoginInvalid',
} as const satisfies Partial<Record<string, TKey>>;

function resourceErrorText(error: unknown, t: T, platform: Platform): string {
  if (platform === 'douyin' && error instanceof ApiError && error.code) {
    const key = douyinResourceErrorKeys[error.code as keyof typeof douyinResourceErrorKeys];
    if (key) return t(key);
  }
  return error instanceof Error ? error.message : String(error);
}

function entryTypeLabel(entry: AccountResourceEntriesResponse['entries'][number], t: T): string {
  if (entry.entry_type === 'favorite_collection') return t('videoCollection');
  if (entry.entry_type === 'multipart_video') return `${t('multipartVideo')} · ${entry.item_count || 1}P`;
  if (entry.entry_type === 'audio') return t('mediaAudio');
  return t('singleVideo');
}

function AccountAvatar({ account, api, large = false }: { account: PlatformAccount; api: ApiClient; large?: boolean }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [account.id, account.avatar_url]);
  return <span className={`account-avatar${large ? ' large' : ''}`}>
    {account.avatar_url && !failed
      ? <img src={api.accountAvatarUrl(account.id)} alt="" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
      : <UserRound aria-hidden="true" />}
  </span>;
}

function ResourceCover({ accountId, resource, api }: { accountId: string; resource: AccountResource; api: ApiClient }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [accountId, resource.id, resource.cover_url]);
  return <span className="resource-cover">
    {resource.cover_url && !failed
      ? <img src={api.accountImageUrl(accountId, resource.cover_url)} alt="" onError={() => setFailed(true)} />
      : <FolderHeart aria-hidden="true" />}
  </span>;
}

export function AccountsPage({ api, health, t, onAnalyze, onTask }: AccountsPageProps) {
  const [accounts, setAccounts] = useState<PlatformAccount[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [kind, setKind] = useState<ResourceKind>('created_favorite');
  const [resources, setResources] = useState<AccountResource[]>([]);
  const [resourceTotal, setResourceTotal] = useState(0);
  const [resourceOffset, setResourceOffset] = useState(0);
  const [opened, setOpened] = useState<AccountResourceEntriesResponse | null>(null);
  const [entryOffset, setEntryOffset] = useState(0);
  const [selectedEntryIds, setSelectedEntryIds] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [addPlatform, setAddPlatform] = useState<Platform>('bilibili');
  const [label, setLabel] = useState('');
  const [cookieContent, setCookieContent] = useState('');
  const [makeDefault, setMakeDefault] = useState(false);
  const [addMethod, setAddMethod] = useState<'qr' | 'cookie'>('qr');
  const [qrChallenge, setQrChallenge] = useState<{ id: string; url: string; expiresAt: string } | null>(null);
  const [qrStatus, setQrStatus] = useState<string | null>(null);
  const [qrTargetAccountId, setQrTargetAccountId] = useState<string | null>(null);
  const [replacingCookies, setReplacingCookies] = useState(false);
  const [replacementCookieContent, setReplacementCookieContent] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const resourceRequest = useRef(0);
  const entryRequest = useRef(0);
  const selected = accounts.find((account) => account.id === selectedId) || null;

  async function loadAccounts(preferredId?: string) {
    const items = await api.accounts();
    setAccounts(items);
    const requestedId = preferredId || selectedId;
    setSelectedId(requestedId && items.some((item) => item.id === requestedId) ? requestedId : items[0]?.id || null);
  }

  async function loadResources(accountId: string, nextKind = kind, offset = 0) {
    const requestId = ++resourceRequest.current;
    entryRequest.current += 1;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const resourceAccount = accounts.find((item) => item.id === accountId);
      const result = await api.accountResources(accountId, nextKind, offset, pageSizeForPlatform(resourceAccount?.platform || 'bilibili'));
      if (requestId !== resourceRequest.current) return;
      setResources(result.items);
      setResourceTotal(result.page.total);
      setResourceOffset(offset);
      setOpened(null);
      setSelectedEntryIds([]);
      if (resourceAccount?.platform === 'douyin' && nextKind !== 'douyin_collections' && result.items[0]) {
        await openResource(result.items[0], 0);
      }
    } catch (err) {
      if (requestId === resourceRequest.current) {
        const platform = accounts.find((item) => item.id === accountId)?.platform || 'bilibili';
        setError(resourceErrorText(err, t, platform));
        setResources([]);
        setResourceTotal(0);
        try { await loadAccounts(accountId); } catch { /* Keep the resource error visible. */ }
      }
    } finally {
      if (requestId === resourceRequest.current) setBusy(false);
    }
  }

  async function openResource(resource: AccountResource, offset = 0) {
    const requestId = ++entryRequest.current;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.accountResourceEntries(resource.account_id, resource.id, offset, pageSizeForPlatform(resource.platform), resource.item_count);
      if (requestId !== entryRequest.current) return;
      const total = Math.max(result.page.total, result.resource.item_count ?? 0, resource.item_count ?? 0);
      setOpened({
        ...result,
        resource: {
          ...result.resource,
          title: resource.title,
          cover_url: result.resource.cover_url || resource.cover_url,
          item_count: total,
        },
        page: { ...result.page, total, has_more: offset + result.entries.length < total },
      });
      setEntryOffset(offset);
      setSelectedEntryIds([]);
    } catch (err) {
      if (requestId === entryRequest.current) {
        const platform = accounts.find((item) => item.id === resource.account_id)?.platform || resource.platform;
        setError(resourceErrorText(err, t, platform));
        try { await loadAccounts(resource.account_id); } catch { /* Keep the entry error visible. */ }
      }
    } finally {
      if (requestId === entryRequest.current) setBusy(false);
    }
  }

  useEffect(() => { void loadAccounts().catch((err) => setError(err instanceof Error ? err.message : String(err))); }, [api]);
  useEffect(() => {
    setReplacingCookies(false);
    setReplacementCookieContent('');
    setQrChallenge(null);
    setQrStatus(null);
    setQrTargetAccountId(null);
    setNotice(null);
  }, [selectedId]);
  useEffect(() => {
    if (!selectedId || !selected) return;
    if (selected.state === 'invalid' || selected.state === 'expired') {
      resourceRequest.current += 1;
      entryRequest.current += 1;
      setResources([]);
      setResourceTotal(0);
      setOpened(null);
      setSelectedEntryIds([]);
      setError(t('accountLoginInvalidHint'));
      setBusy(false);
      return;
    }
    if (selected.platform === 'douyin' && health?.douyin_browser_available !== true) {
      resourceRequest.current += 1;
      entryRequest.current += 1;
      setResources([]);
      setResourceTotal(0);
      setOpened(null);
      setSelectedEntryIds([]);
      setError(null);
      setBusy(false);
      return;
    }
    const nextKind: ResourceKind = selected.platform === 'douyin' ? 'douyin_works' : 'created_favorite';
    setKind(nextKind);
    void loadResources(selectedId, nextKind, 0);
  }, [selectedId, selected?.state, selected?.platform, health?.douyin_browser_available]);

  async function startQrLogin() {
    const targetAccount = qrTargetAccountId ? accounts.find((account) => account.id === qrTargetAccountId) : null;
    const nextLabel = targetAccount?.label || label.trim();
    if (!nextLabel) return;
    setBusy(true);
    setError(null);
    setQrStatus(t('qrWaitingScan'));
    try {
      const result = await api.startBilibiliQr(nextLabel, targetAccount?.is_default ?? makeDefault, targetAccount?.id);
      setQrChallenge({ id: result.challenge_id, url: result.qr_url, expiresAt: result.expires_at });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setQrStatus(null);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!qrChallenge) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const result = await api.pollBilibiliQr(qrChallenge.id);
        if (cancelled) return;
        setQrStatus(t(result.status === 'scanned' ? 'qrScanned' : result.status === 'expired' ? 'qrExpired' : result.status === 'completed' ? 'qrCompleted' : 'qrWaitingScan'));
        if (result.status === 'completed' && result.account) {
          setAdding(false);
          setQrChallenge(null);
          setQrTargetAccountId(null);
          setLabel('');
          setMakeDefault(false);
          await loadAccounts(result.account.id);
          return;
        }
        if (result.status === 'expired') return;
        window.setTimeout(poll, 2000);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    };
    const timer = window.setTimeout(poll, 1000);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [qrChallenge?.id]);

  async function createAccount() {
    setBusy(true);
    setError(null);
    try {
      const account = await api.createAccount({ platform: addPlatform, label: label.trim(), cookie_content: cookieContent, make_default: makeDefault });
      setAdding(false);
      setLabel('');
      setCookieContent('');
      setMakeDefault(false);
      await loadAccounts(account.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function refreshAccount() {
    if (!selected) return;
    await accountAction(() => api.refreshAccount(selected.id));
  }

  async function replaceAccountCookies() {
    if (!selected || !replacementCookieContent.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateAccount(selected.id, { cookie_content: replacementCookieContent });
      setReplacementCookieContent('');
      setReplacingCookies(false);
      await loadAccounts(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      try { await loadAccounts(selected.id); } catch { /* Preserve the replacement error. */ }
    } finally {
      setBusy(false);
    }
  }

  async function accountAction(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      await loadAccounts(selectedId || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      try { await loadAccounts(selectedId || undefined); } catch { /* Preserve the original action error. */ }
    } finally {
      setBusy(false);
    }
  }

  function downloadOptions(resource: AccountResource, entries: AccountResourceEntriesResponse['entries']) {
    return {
      url: resource.source_url, account_id: selected?.id || null, mode: 'video' as const, output_format: 'mp4', audio_format: 'mp3',
      subtitle_langs: [], merge_subtitles: false, save_thumbnail: false, save_description: false,
      embed_chapters: true, audio_normalization: false, concurrent_fragments: 4,
      playlist_title: resource.title, playlist_entries: entries,
      filename_template: '%(playlist_title)s/%(playlist_index)02d-%(title)s_%(resolution)s_[%(id)s].%(ext)s',
    };
  }

  async function downloadSelected() {
    if (!selected || !opened) return;
    const selectedSet = new Set(selectedEntryIds);
    const entries = opened.entries.filter((entry) => isEntryDownloadable(entry) && selectedSet.has(entry.id!)).map((entry, index) => ({ ...entry, index: index + 1 }));
    if (!entries.length) return;
    setBusy(true);
    setError(null);
    try {
      const task = await api.createTask(downloadOptions(opened.resource, entries));
      onTask(task);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function downloadAndMonitor() {
    if (!selected || !opened) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.createMonitor({
        url: opened.resource.source_url, account_id: selected.id, interval_minutes: 60,
        download_options: downloadOptions(opened.resource, []),
      });
      if (result.initial_task) onTask(result.initial_task);
      else setNotice(t('emptyCollectionMonitorCreated'));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function chooseKind(nextKind: ResourceKind) {
    if (!selectedId || !selected) return;
    setKind(nextKind);
    if (selected.state === 'invalid' || selected.state === 'expired') return;
    if (selected.platform === 'douyin' && health?.douyin_browser_available !== true) return;
    void loadResources(selectedId, nextKind, 0);
  }

  function qrLoginPanel() {
    return <div className="account-qr-login">{qrChallenge ? <><span className="account-qr-code"><QRCodeSVG value={qrChallenge.url} size={300} level="L" boostLevel={false} marginSize={4} bgColor="#ffffff" fgColor="#000000" /></span><strong>{qrStatus || t('qrWaitingScan')}</strong><small>{t('qrUseBilibiliApp')}</small><a href={qrChallenge.url} target="_blank" rel="noreferrer"><ExternalLink />{t('openQrLoginLink')}</a><button disabled={busy} onClick={() => void startQrLogin()}><RefreshCw />{t('refreshQrCode')}</button></> : <><QrCode /><strong>{t(qrTargetAccountId ? 'qrReloginTitle' : 'qrLoginRecommended')}</strong><small>{t(qrTargetAccountId ? 'qrReloginHint' : 'qrLoginAutoRenewHint')}</small><button className="primary" disabled={busy || (!qrTargetAccountId && !label.trim())} onClick={() => void startQrLogin()}>{busy ? <LoaderCircle className="spin" /> : <QrCode />}{t('generateQrCode')}</button></>}</div>;
  }

  return <div className="accounts-console">
    <aside className={`account-master ${opened || adding ? 'mobile-hidden' : ''}`}>
      <header><div><span>{t('platformAccounts')}</span><strong>{accounts.length}</strong></div><button className="icon-button" onClick={() => { setQrTargetAccountId(null); setError(null); setNotice(null); setAdding(true); }} title={t('addAccount')}><Plus aria-hidden="true" /></button></header>
      <div className="account-list">{accounts.map((account) => <button key={account.id} className={`account-list-item ${account.id === selectedId ? 'active' : ''}`} onClick={() => setSelectedId(account.id)}><AccountAvatar account={account} api={api} /><span><strong>{account.label}</strong><small>{platformName(account.platform, t)} · {account.display_name || account.external_id || t('unverifiedAccount')}</small></span><span className={`account-state-label ${stateClass(account)}`}><span aria-hidden="true" />{t(accountStateKey(account))}</span></button>)}</div>
      {!accounts.length && <div className="account-empty"><UserRound aria-hidden="true" /><strong>{t('noAccounts')}</strong><button className="primary" onClick={() => { setQrTargetAccountId(null); setError(null); setNotice(null); setAdding(true); }}><Plus aria-hidden="true" />{t('addAccount')}</button></div>}
    </aside>

    <main className="account-detail">
      {error && <p className="account-error">{error}</p>}
      {notice && <p className="account-notice"><CheckCircle2 aria-hidden="true" />{notice}</p>}
      {adding && <section className="account-add-form"><header><div><h2>{t('addPlatformAccount')}</h2><p>{t(addPlatform === 'bilibili' ? 'accountLoginMethodHint' : 'douyinCookieImportHint')}</p></div><button onClick={() => { setAdding(false); setQrChallenge(null); setQrStatus(null); }}>{t('cancel')}</button></header><div><div className="account-add-methods"><button className={addPlatform === 'bilibili' ? 'active' : ''} onClick={() => { setAddPlatform('bilibili'); setAddMethod('qr'); }}>{t('platformBilibili')}</button><button className={addPlatform === 'douyin' ? 'active' : ''} onClick={() => { setAddPlatform('douyin'); setAddMethod('cookie'); setQrChallenge(null); }}>{t('platformDouyin')}</button></div><label>{t('accountLabel')}<input value={label} onChange={(event) => setLabel(event.target.value)} /></label>{addPlatform === 'bilibili' && <div className="account-add-methods"><button className={addMethod === 'qr' ? 'active' : ''} onClick={() => setAddMethod('qr')}><QrCode />{t('qrLogin')}</button><button className={addMethod === 'cookie' ? 'active' : ''} onClick={() => { setAddMethod('cookie'); setQrChallenge(null); }}><Upload />{t('cookieImport')}</button></div>}{addPlatform === 'bilibili' && addMethod === 'qr' ? qrLoginPanel() : <><label>{t('cookieData')}<textarea value={cookieContent} onChange={(event) => setCookieContent(event.target.value)} placeholder={t('cookiePastePlaceholder')} /></label><label className="file-button"><input type="file" accept=".txt,.cookies,.json" onChange={(event) => event.target.files?.[0]?.text().then(setCookieContent)} /><Upload aria-hidden="true" />{t('chooseCookieFile')}</label></>}<label className="check"><input type="checkbox" checked={makeDefault} onChange={(event) => setMakeDefault(event.target.checked)} />{t('setDefaultAccount')}</label></div>{(addPlatform === 'douyin' || addMethod === 'cookie') && <footer><button className="primary" disabled={busy || !label.trim() || !cookieContent.trim()} onClick={() => void createAccount()}>{busy ? <LoaderCircle className="spin" /> : <ShieldCheck />}{t('verifyAndAdd')}</button></footer>}</section>}

      {!adding && selected && <>
        <section className="account-identity"><AccountAvatar account={selected} api={api} large /><div><span>{selected.label}{selected.is_default && <small className="badge blue">{t('defaultAccount')}</small>}<small className="badge">{platformName(selected.platform, t)}</small><small className={`account-state-label ${stateClass(selected)}`}><span aria-hidden="true" />{t(accountStateKey(selected))}</small><small className={`badge ${selected.auto_refresh ? 'blue' : ''}`}>{t(selected.auto_refresh ? 'autoRenewEnabled' : 'manualCookieAccount')}</small></span><h2>{selected.display_name || t('unverifiedAccount')}</h2><p>ID {selected.external_id || '-'}{selected.platform === 'bilibili' ? ` · ${selected.vip_type ? t('premiumAccount') : t('standardAccount')}` : ''}{selected.last_refresh_at ? ` · ${t('lastRenewed')} ${new Date(selected.last_refresh_at).toLocaleString()}` : ''}</p>{selected.last_error && <p className={selected.state === 'invalid' || selected.state === 'expired' ? 'account-refresh-error' : 'account-verification-note'}>{selected.last_error}</p>}{selected.last_refresh_error && <p className="account-refresh-error">{selected.last_refresh_error}</p>}</div><div className="account-actions"><button onClick={() => void accountAction(() => api.verifyAccount(selected.id))}><RefreshCw />{t('verifyAccount')}</button>{selected.platform === 'bilibili' && <button onClick={() => { setReplacingCookies(false); setQrChallenge(null); setQrStatus(null); setQrTargetAccountId((current) => current === selected.id ? null : selected.id); }}><QrCode />{t('qrRelogin')}</button>}{selected.auto_refresh && <button onClick={() => void refreshAccount()}><KeyRound />{t('renewNow')}</button>}<button onClick={() => { const next = window.prompt(t('accountLabel'), selected.label); if (next?.trim() && next.trim() !== selected.label) void accountAction(() => api.updateAccount(selected.id, { label: next.trim() })); }}><Pencil />{t('renameAccount')}</button><button onClick={() => setReplacingCookies((value) => !value)}><Upload />{t('replaceAccountCookies')}</button>{!selected.is_default && <button onClick={() => void accountAction(() => api.setDefaultAccount(selected.id))}><Star />{t('setDefaultAccount')}</button>}<button className="danger" onClick={() => { if (window.confirm(t('deleteAccountConfirm'))) void accountAction(() => api.deleteAccount(selected.id).then(() => { setSelectedId(null); })); }}><Trash2 />{t('deleteAccount')}</button></div></section>
        {selected.platform === 'bilibili' && qrTargetAccountId === selected.id && <section className="account-relogin"><header><div><h3>{t('qrReloginTitle')}</h3><p>{t('qrReloginHint')}</p></div><button onClick={() => { setQrTargetAccountId(null); setQrChallenge(null); setQrStatus(null); }}>{t('cancel')}</button></header>{qrLoginPanel()}</section>}
        {replacingCookies && <section className="account-cookie-editor"><header><div><h3>{t('replaceAccountCookies')}</h3><p>{t('accountCookieHint')}</p></div><button onClick={() => { setReplacingCookies(false); setReplacementCookieContent(''); }}>{t('cancel')}</button></header><label>{t('cookieData')}<textarea autoFocus value={replacementCookieContent} onChange={(event) => setReplacementCookieContent(event.target.value)} placeholder={t('cookiePastePlaceholder')} /></label><footer><label className="file-button"><input type="file" accept=".txt,.cookies,.json" onChange={(event) => event.target.files?.[0]?.text().then(setReplacementCookieContent)} /><Upload aria-hidden="true" />{t('chooseCookieFile')}</label><button className="primary" disabled={busy || !replacementCookieContent.trim()} onClick={() => void replaceAccountCookies()}>{busy ? <LoaderCircle className="spin" /> : <ShieldCheck />}{t('saveAndVerifyCookies')}</button></footer></section>}
        {selected.platform === 'douyin' && <>
          <nav className="account-resource-tabs compact-resource-tabs">{douyinResourceKinds.map((item) => <button key={item} className={kind === item ? 'active' : ''} onClick={() => chooseKind(item)}>{t(item === 'douyin_works' ? 'douyinWorks' : item === 'douyin_favorites' ? 'douyinFavorites' : 'douyinCollections')}</button>)}</nav>
          {health?.douyin_browser_available === false
            ? <section className="account-resources"><div className="account-runtime-status"><AlertTriangle aria-hidden="true" /><div><strong>{t('douyinBrowserUnavailableTitle')}</strong><p>{t('douyinBrowserUnavailableHint')}</p></div></div></section>
            : health?.douyin_browser_available == null
              ? <section className="account-resources"><div className="account-loading"><LoaderCircle className="spin" />{t('checkingBrowserRuntime')}</div></section>
              : !opened
              ? <section className="account-resources"><div className="account-resource-list">{busy && <div className="account-loading"><LoaderCircle className="spin" />{t('working')}</div>}{!busy && resources.map((resource) => <button key={resource.id} className="account-resource-row" onClick={() => void openResource(resource)}><ResourceCover accountId={selected.id} resource={resource} api={api} /><span><strong>{resource.title}</strong><small>{resource.item_count == null ? t('openResource') : `${resource.item_count} ${t('playlistItems')}`}</small></span><ChevronLeft className="resource-chevron" /></button>)}{!busy && !resources.length && <div className="account-empty"><FolderHeart /><strong>{t('noResources')}</strong></div>}</div>{kind === 'douyin_collections' && <div className="account-pagination"><button disabled={resourceOffset === 0 || busy} onClick={() => void loadResources(selected.id, kind, Math.max(0, resourceOffset - douyinPageSize))}>{t('previousPage')}</button><span>{resourceTotal ? `${resourceOffset + 1}-${Math.min(resourceOffset + douyinPageSize, resourceTotal)} / ${resourceTotal}` : '0 / 0'}</span><button disabled={resourceOffset + douyinPageSize >= resourceTotal || busy} onClick={() => void loadResources(selected.id, kind, resourceOffset + douyinPageSize)}>{t('nextPage')}</button></div>}</section>
              : <section className="account-entries douyin-entries"><header><button className="icon-button" onClick={() => { setOpened(null); setSelectedEntryIds([]); }} title={t('back')}><ChevronLeft /></button><div><h2>{opened.resource.title}</h2><p>{opened.page.total} {t('playlistItems')}</p></div><a className="icon-button" href={opened.resource.source_url} target="_blank" rel="noreferrer" title={t('sourcePage')}><ExternalLink /></a></header><div className="account-entry-list">{busy && <div className="account-loading"><LoaderCircle className="spin" />{t('working')}</div>}{!busy && opened.entries.map((entry) => { const entryUrl = canonicalEntryUrl(entry); const imageAlbum = entry.entry_type === 'image_album'; const available = entry.is_available !== false && Boolean(entryUrl); return <div key={`${entry.index}-${entry.id || entryUrl || 'unavailable'}`} className={`douyin-entry-row${available ? '' : ' unavailable'}`}><span className="douyin-entry-index">{entry.index}</span><div><strong>{entry.title || t('untitledVideo')}</strong><small>{entry.channel || t('unknownCreator')}{entry.duration ? ` · ${formatDuration(entry.duration)}` : ''}</small>{!available && <small className="douyin-unavailable-reason">{imageAlbum ? t('douyinImagePost') : entry.unavailable_reason || t('videoUnavailable')}</small>}</div>{imageAlbum && entry.webpage_url ? <a className="button-link" href={entry.webpage_url} target="_blank" rel="noreferrer"><ExternalLink aria-hidden="true" />{t('openSourceLink')}</a> : <button className="primary" disabled={!available} onClick={() => entryUrl && onAnalyze(entryUrl, selected.id)}><Sparkles aria-hidden="true" />{t('analyzeAndDownload')}</button>}</div>; })}{!busy && !opened.entries.length && <div className="account-empty"><FolderHeart /><strong>{t('noResources')}</strong></div>}</div><div className="account-pagination"><button disabled={entryOffset === 0 || busy} onClick={() => void openResource(opened.resource, Math.max(0, entryOffset - douyinPageSize))}>{t('previousPage')}</button><span>{opened.page.total ? `${entryOffset + 1}-${Math.min(entryOffset + opened.entries.length, opened.page.total)} / ${opened.page.total}` : '0 / 0'}</span><button disabled={!opened.page.has_more || busy} onClick={() => void openResource(opened.resource, entryOffset + douyinPageSize)}>{t('nextPage')}</button></div></section>}
        </>}
        {selected.platform === 'bilibili' && <><nav className="account-resource-tabs">{bilibiliResourceKinds.map((item) => <button key={item} className={kind === item ? 'active' : ''} onClick={() => chooseKind(item)}>{t(item === 'created_favorite' ? 'createdFavorites' : item === 'collected_favorite' ? 'collectedFavorites' : item === 'collection' ? 'accountCollections' : 'watchLater')}</button>)}</nav>
        {!opened ? <section className="account-resources"><div className="account-resource-list">{busy && <div className="account-loading"><LoaderCircle className="spin" />{t('working')}</div>}{!busy && resources.map((resource) => <button key={resource.id} className="account-resource-row" onClick={() => void openResource(resource)}><ResourceCover accountId={selected.id} resource={resource} api={api} /><span><strong>{resource.title}</strong><small>{resource.owner_name || selected.display_name} · {resource.item_count ?? 0} {t('playlistItems')}</small></span>{resource.is_private && <span className="badge">{t('privateResource')}</span>}<ChevronLeft className="resource-chevron" /></button>)}{!busy && !resources.length && <div className="account-empty"><FolderHeart /><strong>{t('noResources')}</strong></div>}</div><div className="account-pagination"><button disabled={resourceOffset === 0 || busy} onClick={() => void loadResources(selected.id, kind, Math.max(0, resourceOffset - bilibiliPageSize))}>{t('previousPage')}</button><span>{resourceTotal ? `${resourceOffset + 1}-${Math.min(resourceOffset + bilibiliPageSize, resourceTotal)} / ${resourceTotal}` : '0 / 0'}</span><button disabled={resourceOffset + bilibiliPageSize >= resourceTotal || busy} onClick={() => void loadResources(selected.id, kind, resourceOffset + bilibiliPageSize)}>{t('nextPage')}</button></div></section>
        : <section className="account-entries"><header><button className="icon-button" onClick={() => { setOpened(null); setSelectedEntryIds([]); }} title={t('back')}><ChevronLeft /></button><div><h2>{opened.resource.title}</h2><p>{opened.page.total} {t('playlistItems')}</p></div><a className="icon-button" href={opened.resource.source_url} target="_blank" rel="noreferrer" title={t('sourcePage')}><ExternalLink /></a></header><div className="account-entry-toolbar"><label className="check"><input type="checkbox" checked={opened.entries.some(isEntryDownloadable) && opened.entries.filter(isEntryDownloadable).every((entry) => selectedEntryIds.includes(entry.id!))} onChange={(event) => setSelectedEntryIds(event.target.checked ? opened.entries.filter(isEntryDownloadable).map((entry) => entry.id!) : [])} />{t('selectCurrentPage')}</label><span><button disabled={busy} onClick={() => void downloadAndMonitor()}><Radar />{t('createMonitor')}</button><button className="primary" disabled={!selectedEntryIds.length || busy} onClick={() => void downloadSelected()}><Download />{t('downloadSelected')} ({selectedEntryIds.length})</button></span></div><div className="account-entry-list">{opened.entries.map((entry) => { const downloadable = isEntryDownloadable(entry); return <label key={`${entry.index}-${entry.id}`} className={downloadable ? '' : 'unavailable'}><input type="checkbox" disabled={!downloadable} checked={Boolean(downloadable && entry.id && selectedEntryIds.includes(entry.id))} onChange={() => downloadable && entry.id && setSelectedEntryIds((current) => current.includes(entry.id!) ? current.filter((id) => id !== entry.id) : [...current, entry.id!])} /><span>{entry.index}</span><span><span className="account-entry-title"><strong>{entry.title || entry.id}</strong><small className={`badge ${entry.entry_type === 'favorite_collection' || entry.entry_type === 'multipart_video' ? 'blue' : ''}`}>{entryTypeLabel(entry, t)}</small>{!downloadable && <small className="badge red">{t(entry.entry_type === 'audio' ? 'unsupportedFavoriteItem' : 'videoUnavailable')}</small>}</span><small>{entry.channel || '-'}{entry.duration ? ` · ${formatDuration(entry.duration)}` : ''}</small></span></label>; })}</div><div className="account-pagination"><button disabled={entryOffset === 0 || busy} onClick={() => void openResource(opened.resource, Math.max(0, entryOffset - bilibiliPageSize))}>{t('previousPage')}</button><span>{entryOffset + 1}-{Math.min(entryOffset + bilibiliPageSize, opened.page.total)} / {opened.page.total}</span><button disabled={!opened.page.has_more || busy} onClick={() => void openResource(opened.resource, entryOffset + bilibiliPageSize)}>{t('nextPage')}</button></div></section>}</>}
      </>}
      {!adding && !selected && !!accounts.length && <div className="account-empty"><CheckCircle2 /><strong>{t('selectAccount')}</strong></div>}
    </main>
  </div>;
}
