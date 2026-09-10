import { ArrowLeft, ChevronRight, Copy, Download, Folder, HardDrive, ListVideo, MonitorPlay, Music2, Play, RefreshCw, Search } from 'lucide-react';
import { Fragment, useEffect, useMemo, useRef, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { FileEntry } from '../../api/types';
import type { T } from '../../i18n';
import { formatBytes, mediaLabel } from '../../shared/format';
import { fileDirectory, playlistMeta, withAuthUrl } from '../../shared/media';
import { useMediaPlayer } from './useMediaPlayer';

interface PlayerPageProps {
  current: FileEntry | null;
  queue: FileEntry[];
  folder: string;
  token: string;
  api: ApiClient;
  t: T;
  onSelect: (file: FileEntry | null) => void;
  onQueue: (files: FileEntry[]) => void;
  onFolder: (folder: string) => void;
}

function immediateChildren(folders: string[], parent: string): string[] {
  const prefix = parent ? `${parent}/` : '';
  return folders.filter((path) => {
    if (!path.startsWith(prefix) || path === parent) return false;
    return !path.slice(prefix.length).includes('/');
  });
}

function relativeDirectory(file: FileEntry, folder: string): string {
  const directory = fileDirectory(file);
  if (!folder) return directory;
  if (directory === folder) return '';
  return directory.startsWith(`${folder}/`) ? directory.slice(folder.length + 1) : directory;
}

export function PlayerPage({ current, queue, folder, token, api, t, onSelect, onQueue, onFolder }: PlayerPageProps) {
  const [folders, setFolders] = useState<string[]>([]);
  const [includeSubfolders, setIncludeSubfolders] = useState(true);
  const [queueQuery, setQueueQuery] = useState('');
  const [sideView, setSideView] = useState<'folders' | 'queue'>(() => current ? 'queue' : 'folders');
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState('');
  const listBodyRef = useRef<HTMLDivElement>(null);
  const activeItemRef = useRef<HTMLButtonElement>(null);
  const initialLoadRef = useRef(false);
  const loadSequenceRef = useRef(0);
  const active = current;
  const childFolders = useMemo(() => immediateChildren(folders, folder), [folders, folder]);
  const filteredQueue = useMemo(() => {
    const query = queueQuery.trim().toLowerCase();
    return query ? queue.filter((file) => `${file.name}\n${file.relative_path}`.toLowerCase().includes(query)) : queue;
  }, [queue, queueQuery]);
  const navigationQueue = queueQuery.trim() ? filteredQueue : queue;
  const activeIndex = active ? navigationQueue.findIndex((file) => file.id === active.id) : -1;
  const queueIndexes = useMemo(() => new Map(queue.map((file, index) => [file.id, index + 1])), [queue]);
  const groupCounts = useMemo(() => filteredQueue.reduce((counts, file) => {
    const group = relativeDirectory(file, folder);
    counts.set(group, (counts.get(group) || 0) + 1);
    return counts;
  }, new Map<string, number>()), [filteredQueue, folder]);
  const breadcrumbParts = folder.split('/').filter(Boolean);
  const { containerRef, videoFit, videoAspectRatio, setVideoFit } = useMediaPlayer(active, token);

  function selectRelative(offset: number) {
    const next = navigationQueue[activeIndex + offset];
    if (next) onSelect(next);
  }

  async function loadFolder(nextFolder: string, recursive = includeSubfolders, preferredId?: string, revealQueue = false) {
    const sequence = ++loadSequenceRef.current;
    const directOnly = !nextFolder || !recursive;
    const changingFolder = nextFolder !== folder;
    setLoading(true);
    setLoadError('');
    if (changingFolder) setQueueQuery('');
    if (revealQueue) setSideView('queue');
    onFolder(nextFolder);
    try {
      const first = await api.files('', nextFolder, 0, 200, true, directOnly);
      const files = [...first.files];
      for (let offset = first.files.length; offset < first.total; offset += 200) {
        const page = await api.files('', nextFolder, offset, 200, true, directOnly);
        files.push(...page.files);
      }
      if (sequence !== loadSequenceRef.current) return;
      setFolders(first.folders);
      const mediaFiles = files.filter((file) => file.playable && (file.media_type === 'video' || file.media_type === 'audio'));
      onQueue(mediaFiles);
      if (preferredId) onSelect(mediaFiles.find((file) => file.id === preferredId) || null);
      if (revealQueue && !mediaFiles.length) setSideView('folders');
      listBodyRef.current?.scrollTo({ top: 0 });
    } catch (error) {
      if (sequence !== loadSequenceRef.current) return;
      if (revealQueue) setSideView('folders');
      setLoadError(error instanceof Error ? error.message : t('playerLoadFailed'));
    } finally {
      if (sequence === loadSequenceRef.current) setLoading(false);
    }
  }

  function changeScope(recursive: boolean) {
    setIncludeSubfolders(recursive);
    void loadFolder(folder, recursive, active?.id, true);
  }

  useEffect(() => {
    if (initialLoadRef.current) return;
    initialLoadRef.current = true;
    void loadFolder(folder, includeSubfolders, active?.id);
  }, []);
  useEffect(() => {
    const listBody = listBodyRef.current;
    const activeItem = activeItemRef.current;
    if (!listBody || !activeItem || window.matchMedia('(max-width: 720px)').matches) return;
    const itemTop = activeItem.offsetTop;
    const itemBottom = itemTop + activeItem.offsetHeight;
    if (itemTop < listBody.scrollTop) listBody.scrollTo({ top: itemTop, behavior: 'smooth' });
    else if (itemBottom > listBody.scrollTop + listBody.clientHeight) listBody.scrollTo({ top: itemBottom - listBody.clientHeight, behavior: 'smooth' });
  }, [active?.id, queue.length]);

  let previousGroup: string | null = null;

  return <div className={`watch-layout ${active ? 'has-active-media' : 'is-empty'}`}>
    <section className="watch-main">
      <div className="watch-stage">
        <div className="watch-player-shell" style={{ aspectRatio: active?.media_type === 'video' ? String(videoAspectRatio) : '16 / 9' }}>
          {!active && <div className="watch-empty"><span className="watch-empty-icon"><MonitorPlay size={26} aria-hidden="true" /></span><h2>{loading ? t('working') : t('selectPlayable')}</h2></div>}
          {active && <div className={`art-player-host ${active.media_type === 'audio' ? 'audio-mode' : ''}`} ref={containerRef} />}
        </div>
      </div>
      {active && <div className="watch-meta">
        <div className="watch-title-block"><span className="watch-now-playing">{t('player')}</span><h2 title={active.name}>{active.name}</h2><p className="muted">{playlistMeta(active, t)}</p></div>
        <div className="watch-actions">
          {active.media_type === 'video' && <div className="watch-fit-control" aria-label={t('player')}><button className={videoFit === 'cover' ? 'active' : ''} onClick={() => setVideoFit('cover')}>{t('playerFill')}</button><button className={videoFit === 'contain' ? 'active' : ''} onClick={() => setVideoFit('contain')}>{t('playerFit')}</button></div>}
          <div className="watch-skip-controls"><button className="icon-button" onClick={() => selectRelative(-1)} disabled={activeIndex <= 0} title={t('previousPage')} aria-label={t('previousPage')}><ChevronRight className="previous-icon" size={17} /></button><span>{activeIndex >= 0 ? `${activeIndex + 1} / ${navigationQueue.length}` : '-'}</span><button className="icon-button" onClick={() => selectRelative(1)} disabled={activeIndex < 0 || activeIndex >= navigationQueue.length - 1} title={t('nextPage')} aria-label={t('nextPage')}><ChevronRight size={17} /></button></div>
          <a className="button-link primary-link" href={withAuthUrl(active.download_url, token)}><Download size={15} />{t('download')}</a>
          <button className="icon-button" onClick={() => navigator.clipboard?.writeText(withAuthUrl(active.download_url, token))} title={t('copyLink')} aria-label={t('copyLink')}><Copy size={15} /></button>
        </div>
      </div>}
    </section>
    <aside className="watch-list">
      <div className="watch-list-header"><div><span className="watch-eyebrow">{t('playerFolder')}</span><h2 title={folder}>{folder.split('/').pop() || t('allFolders')}</h2></div><div className="watch-list-summary"><button className="icon-button" onClick={() => void loadFolder(folder, includeSubfolders, active?.id)} disabled={loading} title={t('refresh')} aria-label={t('refresh')}><RefreshCw className={loading ? 'spin' : ''} /></button></div></div>
      <div className="watch-side-tabs" role="tablist" aria-label={t('playerFolder')}><button className={sideView === 'folders' ? 'active' : ''} onClick={() => setSideView('folders')} role="tab" aria-selected={sideView === 'folders'}><Folder />{t('folderTree')}<small>{childFolders.length}</small></button><button className={sideView === 'queue' ? 'active' : ''} onClick={() => setSideView('queue')} role="tab" aria-selected={sideView === 'queue'}><ListVideo />{t('playQueue')}<small>{queue.length}</small></button></div>
      {loadError && <div className="watch-load-error" title={loadError}>{t('playerLoadFailed')}: {loadError}</div>}
      {sideView === 'folders' && <div className="watch-folder-browser">
        <nav className="watch-breadcrumb" aria-label={t('folderTree')}><button className={!folder ? 'current' : ''} onClick={() => void loadFolder('', false)} title={t('allFolders')}><HardDrive /><span>{t('allFolders')}</span></button>{breadcrumbParts.map((part, index) => { const path = breadcrumbParts.slice(0, index + 1).join('/'); return <span key={path}><ChevronRight /><button className={path === folder ? 'current' : ''} onClick={() => void loadFolder(path, includeSubfolders, undefined, true)} title={path}>{part}</button></span>; })}</nav>
        {folder && <div className="watch-scope-control" role="group" aria-label={t('playerFolder')}><button className={!includeSubfolders ? 'active' : ''} onClick={() => changeScope(false)}>{t('playerCurrentLevel')}</button><button className={includeSubfolders ? 'active' : ''} onClick={() => changeScope(true)}>{t('playerIncludeSubfolders')}</button></div>}
        <div className="watch-folder-section-title"><span>{t('subfolders')}</span><small>{childFolders.length}</small></div>
        <div className="watch-child-folders">{childFolders.map((path) => <button key={path} onClick={() => void loadFolder(path, includeSubfolders, undefined, true)} title={path}><Folder /><span>{path.split('/').pop()}</span><ChevronRight /></button>)}{!loading && !childFolders.length && <div className="watch-folder-empty">{t('noSubfolders')}</div>}</div>
      </div>}
      {sideView === 'queue' && <>
        <div className="watch-queue-context"><button onClick={() => setSideView('folders')}><ArrowLeft />{t('backToFolders')}</button><span title={folder}>{folder ? folder.split('/').pop() : t('allFolders')}</span></div>
        {!!queue.length && <label className="watch-queue-search"><Search /><input value={queueQuery} onChange={(event) => setQueueQuery(event.target.value)} placeholder={t('searchFiles')} /><span>{filteredQueue.length}/{queue.length}</span></label>}
        <div className="watch-list-body" ref={listBodyRef} aria-busy={loading}>
          {loading && <div className="watch-list-loading">{t('working')}</div>}
          {!loading && !queue.length && <div className="watch-queue-empty">{t('selectPlayerFolder')}</div>}
          {!loading && !!queue.length && !filteredQueue.length && <div className="watch-queue-empty">{t('noMatchingMedia')}</div>}
          {!loading && filteredQueue.map((file) => {
            const group = relativeDirectory(file, folder);
            const showGroup = group !== previousGroup;
            previousGroup = group;
            const MediaIcon = file.media_type === 'audio' ? Music2 : MonitorPlay;
            return <Fragment key={file.id}>{showGroup && <div className="watch-queue-group"><strong><Folder /><span title={group || folder}>{group || t('playerCurrentLevel')}</span></strong><small>{groupCounts.get(group)}</small></div>}<button ref={active?.id === file.id ? activeItemRef : undefined} className={`watch-list-item ${active?.id === file.id ? 'active' : ''}`} onClick={() => onSelect(file)}><span className="watch-index">{active?.id === file.id ? <Play size={14} fill="currentColor" /> : queueIndexes.get(file.id)}</span><span className="watch-item-copy"><strong title={file.name}>{file.name}</strong><span><MediaIcon />{mediaLabel(file.media_type, t)} · {formatBytes(file.size)}</span></span></button></Fragment>;
          })}
        </div>
      </>}
    </aside>
  </div>;
}
