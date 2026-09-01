import { ChevronRight, Copy, Download, MonitorPlay, Music2, Play } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { FileEntry } from '../../api/types';
import type { T } from '../../i18n';
import { formatBytes, mediaLabel } from '../../shared/format';
import { playlistMeta, withAuthUrl } from '../../shared/media';
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

export function PlayerPage({ current, queue, folder, token, api, t, onSelect, onQueue, onFolder }: PlayerPageProps) {
  const [folders, setFolders] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const active = current || queue[0] || null;
  const activeIndex = active ? queue.findIndex((file) => file.id === active.id) : -1;
  const { containerRef, videoFit, videoAspectRatio, setVideoFit } = useMediaPlayer(active, token);

  function selectRelative(offset: number) {
    const next = queue[activeIndex + offset];
    if (next) onSelect(next);
  }

  async function loadFolder(nextFolder: string) {
    setLoading(true);
    onFolder(nextFolder);
    try {
      const result = await api.files('', nextFolder, 0, 200, true, true);
      setFolders(result.folders);
      const mediaFiles = result.files.filter((file) => file.playable && (file.media_type === 'video' || file.media_type === 'audio'));
      onQueue(mediaFiles);
      onSelect(mediaFiles[0] || null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (!queue.length) void loadFolder(folder);
  }, []);

  return <div className="watch-layout">
    <section className="watch-main">
      <div className="watch-stage">
        <div className="watch-player-shell" style={{ aspectRatio: active?.media_type === 'video' ? String(videoAspectRatio) : '16 / 9' }}>
          {!active && <div className="watch-empty"><span className="watch-empty-icon"><MonitorPlay size={30} aria-hidden="true" /></span><h2>{t('selectPlayable')}</h2><button className="primary" onClick={() => void loadFolder(folder)}>{t('openFiles')}</button></div>}
          {active && <div className={`art-player-host ${active.media_type === 'audio' ? 'audio-mode' : ''}`} ref={containerRef} />}
        </div>
      </div>
      {active && <div className="watch-meta">
        <div className="watch-title-block"><span className="watch-now-playing">{t('player')}</span><h2 title={active.name}>{active.name}</h2><p className="muted">{playlistMeta(active, t)}</p></div>
        <div className="watch-actions">
          {active.media_type === 'video' && <div className="watch-fit-control" aria-label={t('player')}><button className={videoFit === 'cover' ? 'active' : ''} onClick={() => setVideoFit('cover')}>{t('playerFill')}</button><button className={videoFit === 'contain' ? 'active' : ''} onClick={() => setVideoFit('contain')}>{t('playerFit')}</button></div>}
          <div className="watch-skip-controls"><button className="icon-button" onClick={() => selectRelative(-1)} disabled={activeIndex <= 0} title={t('previousPage')} aria-label={t('previousPage')}><ChevronRight className="previous-icon" size={17} /></button><span>{activeIndex >= 0 ? `${activeIndex + 1} / ${queue.length}` : '-'}</span><button className="icon-button" onClick={() => selectRelative(1)} disabled={activeIndex < 0 || activeIndex >= queue.length - 1} title={t('nextPage')} aria-label={t('nextPage')}><ChevronRight size={17} /></button></div>
          <a className="button-link primary-link" href={withAuthUrl(active.download_url, token)}><Download size={15} />{t('download')}</a>
          <button className="icon-button" onClick={() => navigator.clipboard?.writeText(withAuthUrl(active.download_url, token))} title={t('copyLink')} aria-label={t('copyLink')}><Copy size={15} /></button>
        </div>
      </div>}
    </section>
    <aside className="watch-list">
      <div className="watch-list-header"><div><span className="watch-eyebrow">{t('playerFolder')}</span><h2>{t('playQueue')}</h2></div><span className="queue-count">{queue.length}</span></div>
      <div className="watch-folder-bar"><select value={folder} onChange={(event) => void loadFolder(event.target.value)} aria-label={t('playerFolder')}><option value="">{t('allFolders')}</option>{folders.map((item) => <option key={item} value={item}>{item}</option>)}</select></div>
      <div className="watch-list-body">
        {loading && <div className="watch-queue-empty">{t('working')}</div>}
        {!loading && !queue.length && <div className="watch-queue-empty">{t('selectPlayable')}</div>}
        {!loading && queue.map((file, index) => <button key={file.id} className={`watch-list-item ${active?.id === file.id ? 'active' : ''}`} onClick={() => onSelect(file)}><span className="watch-index">{active?.id === file.id ? <Play size={13} fill="currentColor" /> : index + 1}</span><span className="watch-media-icon">{file.media_type === 'audio' ? <Music2 size={16} /> : <MonitorPlay size={16} />}</span><span className="watch-item-copy"><strong>{file.name}</strong><span>{mediaLabel(file.media_type, t)} · {formatBytes(file.size)}</span></span></button>)}
      </div>
    </aside>
  </div>;
}
