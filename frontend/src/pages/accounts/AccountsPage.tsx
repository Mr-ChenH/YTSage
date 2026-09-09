import { CheckCircle2, ChevronLeft, Download, ExternalLink, FolderHeart, LoaderCircle, Pencil, Plus, Radar, RefreshCw, ShieldCheck, Star, Trash2, Upload, UserRound } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { AccountResource, AccountResourceEntriesResponse, AccountResourceType, PlatformAccount, TaskResponse } from '../../api/types';
import type { T } from '../../i18n';

interface AccountsPageProps {
  api: ApiClient;
  t: T;
  onTask: (task: TaskResponse) => void;
}

type ResourceKind = Extract<AccountResourceType, 'created_favorite' | 'collected_favorite' | 'collection' | 'watch_later'>;
const resourceKinds: ResourceKind[] = ['created_favorite', 'collected_favorite', 'collection', 'watch_later'];
const pageSize = 20;

function stateClass(account: PlatformAccount): string {
  return account.state === 'valid' ? 'valid' : account.state === 'unknown' ? 'warning' : 'error';
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

export function AccountsPage({ api, t, onTask }: AccountsPageProps) {
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
  const [label, setLabel] = useState('');
  const [cookieContent, setCookieContent] = useState('');
  const [makeDefault, setMakeDefault] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
    try {
      const result = await api.accountResources(accountId, nextKind, offset, pageSize);
      if (requestId !== resourceRequest.current) return;
      setResources(result.items);
      setResourceTotal(result.page.total);
      setResourceOffset(offset);
      setOpened(null);
      setSelectedEntryIds([]);
    } catch (err) {
      if (requestId === resourceRequest.current) {
        setError(err instanceof Error ? err.message : String(err));
        setResources([]);
        setResourceTotal(0);
      }
    } finally {
      if (requestId === resourceRequest.current) setBusy(false);
    }
  }

  async function openResource(resource: AccountResource, offset = 0) {
    const requestId = ++entryRequest.current;
    setBusy(true);
    setError(null);
    try {
      const result = await api.accountResourceEntries(resource.account_id, resource.id, offset, pageSize);
      if (requestId !== entryRequest.current) return;
      setOpened({ ...result, resource: { ...result.resource, title: resource.title, cover_url: result.resource.cover_url || resource.cover_url } });
      setEntryOffset(offset);
      setSelectedEntryIds([]);
    } catch (err) {
      if (requestId === entryRequest.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (requestId === entryRequest.current) setBusy(false);
    }
  }

  useEffect(() => { void loadAccounts().catch((err) => setError(err instanceof Error ? err.message : String(err))); }, [api]);
  useEffect(() => { if (selectedId) void loadResources(selectedId, kind, 0); }, [selectedId]);

  async function createAccount() {
    setBusy(true);
    setError(null);
    try {
      const account = await api.createAccount({ platform: 'bilibili', label: label.trim(), cookie_content: cookieContent, make_default: makeDefault });
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

  async function accountAction(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
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
    const entries = opened.entries.filter((entry) => entry.id && selectedSet.has(entry.id)).map((entry, index) => ({ ...entry, index: index + 1 }));
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
    try {
      const result = await api.createMonitor({
        url: opened.resource.source_url, account_id: selected.id, interval_minutes: 60,
        download_options: downloadOptions(opened.resource, []),
      });
      onTask(result.initial_task);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function chooseKind(nextKind: ResourceKind) {
    if (!selectedId) return;
    setKind(nextKind);
    void loadResources(selectedId, nextKind, 0);
  }

  return <div className="accounts-console">
    <aside className={`account-master ${opened || adding ? 'mobile-hidden' : ''}`}>
      <header><div><span>{t('bilibiliAccounts')}</span><strong>{accounts.length}</strong></div><button className="icon-button" onClick={() => setAdding(true)} title={t('addAccount')}><Plus aria-hidden="true" /></button></header>
      <div className="account-list">{accounts.map((account) => <button key={account.id} className={`account-list-item ${account.id === selectedId ? 'active' : ''}`} onClick={() => setSelectedId(account.id)}><AccountAvatar account={account} api={api} /><span><strong>{account.label}</strong><small>{account.display_name || account.external_id || t('unverifiedAccount')}</small></span><span className={`account-state-dot ${stateClass(account)}`} title={t(account.state === 'valid' ? 'accountValid' : account.state === 'unknown' ? 'accountUnknown' : 'accountInvalid')} /></button>)}</div>
      {!accounts.length && <div className="account-empty"><UserRound aria-hidden="true" /><strong>{t('noAccounts')}</strong><button className="primary" onClick={() => setAdding(true)}><Plus aria-hidden="true" />{t('addAccount')}</button></div>}
    </aside>

    <main className="account-detail">
      {error && <p className="account-error">{error}</p>}
      {adding && <section className="account-add-form"><header><div><h2>{t('addBilibiliAccount')}</h2><p>{t('accountCookieHint')}</p></div><button onClick={() => setAdding(false)}>{t('cancel')}</button></header><div><label>{t('accountLabel')}<input value={label} onChange={(event) => setLabel(event.target.value)} /></label><label>{t('cookieData')}<textarea value={cookieContent} onChange={(event) => setCookieContent(event.target.value)} placeholder={t('cookiePastePlaceholder')} /></label><label className="file-button"><input type="file" accept=".txt,.cookies,.json" onChange={(event) => event.target.files?.[0]?.text().then(setCookieContent)} /><Upload aria-hidden="true" />{t('chooseCookieFile')}</label><label className="check"><input type="checkbox" checked={makeDefault} onChange={(event) => setMakeDefault(event.target.checked)} />{t('setDefaultAccount')}</label></div><footer><button className="primary" disabled={busy || !label.trim() || !cookieContent.trim()} onClick={() => void createAccount()}>{busy ? <LoaderCircle className="spin" /> : <ShieldCheck />}{t('verifyAndAdd')}</button></footer></section>}

      {!adding && selected && <>
        <section className="account-identity"><AccountAvatar account={selected} api={api} large /><div><span>{selected.label}{selected.is_default && <small className="badge blue">{t('defaultAccount')}</small>}</span><h2>{selected.display_name || t('unverifiedAccount')}</h2><p>UID {selected.external_id || '-'} · {selected.vip_type ? t('premiumAccount') : t('standardAccount')}</p></div><div className="account-actions"><button onClick={() => void accountAction(() => api.verifyAccount(selected.id))}><RefreshCw />{t('verifyAccount')}</button><button onClick={() => { const next = window.prompt(t('accountLabel'), selected.label); if (next?.trim() && next.trim() !== selected.label) void accountAction(() => api.updateAccount(selected.id, { label: next.trim() })); }}><Pencil />{t('renameAccount')}</button><label className="file-button"><input type="file" accept=".txt,.cookies,.json" onChange={(event) => { const file = event.target.files?.[0]; if (file) void file.text().then((content) => accountAction(() => api.updateAccount(selected.id, { cookie_content: content }))); }} /><Upload />{t('replaceAccountCookies')}</label>{!selected.is_default && <button onClick={() => void accountAction(() => api.setDefaultAccount(selected.id))}><Star />{t('setDefaultAccount')}</button>}<button className="danger" onClick={() => { if (window.confirm(t('deleteAccountConfirm'))) void accountAction(() => api.deleteAccount(selected.id).then(() => { setSelectedId(null); })); }}><Trash2 />{t('deleteAccount')}</button></div></section>
        <nav className="account-resource-tabs">{resourceKinds.map((item) => <button key={item} className={kind === item ? 'active' : ''} onClick={() => chooseKind(item)}>{t(item === 'created_favorite' ? 'createdFavorites' : item === 'collected_favorite' ? 'collectedFavorites' : item === 'collection' ? 'accountCollections' : 'watchLater')}</button>)}</nav>
        {!opened ? <section className="account-resources"><div className="account-resource-list">{busy && <div className="account-loading"><LoaderCircle className="spin" />{t('working')}</div>}{!busy && resources.map((resource) => <button key={resource.id} className="account-resource-row" onClick={() => void openResource(resource)}><span className="resource-cover">{resource.cover_url ? <img src={resource.cover_url} alt="" /> : <FolderHeart />}</span><span><strong>{resource.title}</strong><small>{resource.owner_name || selected.display_name} · {resource.item_count ?? 0} {t('playlistItems')}</small></span>{resource.is_private && <span className="badge">{t('privateResource')}</span>}<ChevronLeft className="resource-chevron" /></button>)}{!busy && !resources.length && <div className="account-empty"><FolderHeart /><strong>{t('noResources')}</strong></div>}</div><div className="account-pagination"><button disabled={resourceOffset === 0 || busy} onClick={() => void loadResources(selected.id, kind, Math.max(0, resourceOffset - pageSize))}>{t('previousPage')}</button><span>{resourceTotal ? `${resourceOffset + 1}-${Math.min(resourceOffset + pageSize, resourceTotal)} / ${resourceTotal}` : '0 / 0'}</span><button disabled={resourceOffset + pageSize >= resourceTotal || busy} onClick={() => void loadResources(selected.id, kind, resourceOffset + pageSize)}>{t('nextPage')}</button></div></section>
        : <section className="account-entries"><header><button className="icon-button" onClick={() => { setOpened(null); setSelectedEntryIds([]); }} title={t('back')}><ChevronLeft /></button><div><h2>{opened.resource.title}</h2><p>{opened.page.total} {t('playlistItems')}</p></div><a className="icon-button" href={opened.resource.source_url} target="_blank" rel="noreferrer" title={t('sourcePage')}><ExternalLink /></a></header><div className="account-entry-toolbar"><label className="check"><input type="checkbox" checked={opened.entries.length > 0 && opened.entries.every((entry) => entry.id && selectedEntryIds.includes(entry.id))} onChange={(event) => setSelectedEntryIds(event.target.checked ? opened.entries.flatMap((entry) => entry.id ? [entry.id] : []) : [])} />{t('selectCurrentPage')}</label><span><button disabled={busy} onClick={() => void downloadAndMonitor()}><Radar />{t('createMonitor')}</button><button className="primary" disabled={!selectedEntryIds.length || busy} onClick={() => void downloadSelected()}><Download />{t('downloadSelected')} ({selectedEntryIds.length})</button></span></div><div className="account-entry-list">{opened.entries.map((entry) => <label key={`${entry.index}-${entry.id}`}><input type="checkbox" disabled={!entry.id || !entry.url} checked={Boolean(entry.id && selectedEntryIds.includes(entry.id))} onChange={() => entry.id && setSelectedEntryIds((current) => current.includes(entry.id!) ? current.filter((id) => id !== entry.id) : [...current, entry.id!])} /><span>{entry.index}</span><span><strong>{entry.title || entry.id}</strong><small>{entry.channel || '-'}{entry.duration ? ` · ${Math.round(entry.duration / 60)} ${t('minutes')}` : ''}</small></span></label>)}</div><div className="account-pagination"><button disabled={entryOffset === 0 || busy} onClick={() => void openResource(opened.resource, Math.max(0, entryOffset - pageSize))}>{t('previousPage')}</button><span>{entryOffset + 1}-{Math.min(entryOffset + pageSize, opened.page.total)} / {opened.page.total}</span><button disabled={!opened.page.has_more || busy} onClick={() => void openResource(opened.resource, entryOffset + pageSize)}>{t('nextPage')}</button></div></section>}
      </>}
      {!adding && !selected && !!accounts.length && <div className="account-empty"><CheckCircle2 /><strong>{t('selectAccount')}</strong></div>}
    </main>
  </div>;
}
