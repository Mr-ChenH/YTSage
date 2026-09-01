import { useEffect, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { FileEntry, FileListResponse } from '../../api/types';
import type { T } from '../../i18n';
import { formatBytes, formatPageInfo, mediaLabel } from '../../shared/format';
import { directParent, withAuthUrl } from '../../shared/media';
import { paginationItems } from '../../shared/pagination';
import { ManifestExport, type ManifestFormat } from './ManifestExport';

interface FilesPageProps {
  library: FileListResponse | null;
  token: string;
  api: ApiClient;
  t: T;
  onLoaded: (library: FileListResponse) => void;
  onPlay: (file: FileEntry, queue: FileEntry[], folder: string) => void;
}

export function FilesPage({ library, token, api, t, onLoaded, onPlay }: FilesPageProps) {
  const [query, setQuery] = useState('');
  const [folder, setFolder] = useState('');
  const [mediaPage, setMediaPage] = useState(1);
  const mediaPageSize = 30;
  const mediaFiles = (library?.files || []).filter((file) => file.playable && (file.media_type === 'video' || file.media_type === 'audio') && directParent(file.relative_path) === folder);
  const mediaPages = Math.max(1, Math.ceil((library?.total || 0) / mediaPageSize));
  const normalizedMediaPage = Math.min(mediaPages, Math.max(1, mediaPage));
  const mediaPageItems = paginationItems(normalizedMediaPage, mediaPages);
  const folderItems = library?.folders || [];
  const folderUrl = folder ? `${api.downloadFolderUrl(folder)}${token ? `&token=${encodeURIComponent(token)}` : ''}` : '#';
  const manifestUrl = (format: ManifestFormat) => folder ? `${api.folderManifestUrl(folder, format)}${token ? `&token=${encodeURIComponent(token)}` : ''}` : '#';
  const aria2Filename = `${(folder.split('/').pop() || folder || 'downloads')}.aria2.txt`;

  async function load(nextOffset = 0, nextQuery = query, nextFolder = folder) {
    onLoaded(await api.files(nextQuery, nextFolder, nextOffset, mediaPageSize, true, true));
  }
  async function changeFolder(value: string) {
    setFolder(value);
    setMediaPage(1);
    await load(0, query, value);
  }
  async function changeMediaPage(nextPage: number) {
    const page = Math.min(mediaPages, Math.max(1, nextPage));
    setMediaPage(page);
    await load((page - 1) * mediaPageSize);
  }
  async function removeFile(file: FileEntry) {
    if (!window.confirm(t('confirmDeleteFile').replace('{name}', file.name))) return;
    await api.deleteFile(file.id);
    setMediaPage(1);
    await load(0);
  }
  async function removeFolder() {
    if (!folder || !window.confirm(t('confirmDeleteFolder').replace('{name}', folder))) return;
    await api.deleteFolder(folder);
    const parent = directParent(folder);
    setFolder(parent);
    setMediaPage(1);
    await load(0, query, parent);
  }
  useEffect(() => {
    if (!library) void load(0);
  }, [library]);

  return <div className="file-browser-grid">
    <aside className="panel acrylic file-tree-panel">
      <div className="panel-header"><h2>{t('folderTree')}</h2><span className="badge blue">{folderItems.length}</span></div>
      <div className="file-tree-list">
        <button className={`tree-item ${folder === '' ? 'active' : ''}`} onClick={() => void changeFolder('')}><span className="tree-indent" style={{ width: 0 }} />{t('allFolders')}</button>
        {folderItems.map((item) => <button className={`tree-item ${folder === item ? 'active' : ''}`} key={item} onClick={() => void changeFolder(item)}><span className="tree-indent" style={{ width: `${Math.max(0, item.split('/').length - 1) * 14}px` }} />{item.split('/').pop() || item}</button>)}
      </div>
    </aside>
    <section className="panel acrylic file-media-panel"><div className="panel-header"><div className="stack"><h2>{t('mediaInFolder')}</h2><span className="muted">{folder || t('allFolders')} - {t('directMediaOnly')}</span></div><div className="toolbar file-toolbar-inline">
      <input value={query} placeholder={t('searchFiles')} onChange={(event) => setQuery(event.target.value)} />
      <button onClick={() => { setMediaPage(1); void load(0); }}>{t('search')}</button>
      <ManifestExport disabled={!folder} manifestUrl={manifestUrl} aria2Filename={aria2Filename} t={t} />
      <a className={`button-link ${folder ? '' : 'disabled'}`} href={folderUrl} aria-disabled={!folder} onClick={(event) => { if (!folder) event.preventDefault(); }}>{t('downloadFolder')}</a>
      <button className="danger" disabled={!folder} onClick={() => void removeFolder()}>{t('deleteFolder')}</button>
    </div></div><div className="panel-body media-table-body">
      {!mediaFiles.length && <div className="empty-state">{t('noFiles')}</div>}
      {!!mediaFiles.length && <div className="media-table-wrap"><table className="media-table"><thead><tr><th>{t('title')}</th><th>{t('type')}</th><th>{t('size')}</th><th></th></tr></thead><tbody>{mediaFiles.map((file) => <tr key={file.id}><td><strong>{file.name}</strong></td><td><span className="badge green">{mediaLabel(file.media_type, t)}</span></td><td>{formatBytes(file.size)}</td><td><div className="toolbar compact-actions"><button onClick={() => onPlay(file, mediaFiles, folder)}>{t('play')}</button><a className="button-link" href={withAuthUrl(file.download_url, token)}>{t('download')}</a><button onClick={() => navigator.clipboard?.writeText(withAuthUrl(file.download_url, token))}>{t('copyLink')}</button><button className="danger" onClick={() => void removeFile(file)}>{t('deleteFile')}</button></div></td></tr>)}</tbody></table></div>}
      <div className="pagination-row"><button onClick={() => void changeMediaPage(normalizedMediaPage - 1)} disabled={normalizedMediaPage <= 1}>{t('previousPage')}</button><span className="muted">{formatPageInfo(t('pageInfo'), normalizedMediaPage, mediaPages, library?.total || 0)}</span><div className="page-list" aria-label="Pagination">{mediaPageItems.map((item, index) => item === 'ellipsis' ? <span className="page-ellipsis" key={`ellipsis-${index}`}>...</span> : <button className={item === normalizedMediaPage ? 'active' : ''} key={item} onClick={() => void changeMediaPage(item)} disabled={item === normalizedMediaPage} aria-current={item === normalizedMediaPage ? 'page' : undefined}>{item}</button>)}</div><button onClick={() => void changeMediaPage(normalizedMediaPage + 1)} disabled={normalizedMediaPage >= mediaPages}>{t('nextPage')}</button></div>
    </div></section>
  </div>;
}
