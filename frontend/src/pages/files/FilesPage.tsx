import { ChevronDown, ChevronRight, Folder, FolderOpen, HardDrive, ListCollapse } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { ApiClient } from '../../api/client';
import type { FileEntry, FileListResponse } from '../../api/types';
import type { T } from '../../i18n';
import { formatBytes, formatPageInfo, mediaLabel } from '../../shared/format';
import { directParent, withAuthUrl } from '../../shared/media';
import { paginationItems } from '../../shared/pagination';
import { ManifestExport, type ManifestFormat } from './ManifestExport';

interface FolderNode {
  name: string;
  path: string;
  children: FolderNode[];
}

function buildFolderTree(folders: string[]): FolderNode[] {
  const roots: FolderNode[] = [];
  const nodes = new Map<string, FolderNode>();
  folders.forEach((folder) => {
    const parts = folder.split('/').filter(Boolean);
    parts.forEach((name, index) => {
      const path = parts.slice(0, index + 1).join('/');
      if (nodes.has(path)) return;
      const node = { name, path, children: [] };
      nodes.set(path, node);
      const parentPath = parts.slice(0, index).join('/');
      const siblings = parentPath ? nodes.get(parentPath)?.children : roots;
      siblings?.push(node);
    });
  });
  const sortNodes = (items: FolderNode[]) => {
    items.sort((left, right) => left.name.localeCompare(right.name));
    items.forEach((item) => sortNodes(item.children));
  };
  sortNodes(roots);
  return roots;
}

interface FolderTreeNodeProps {
  node: FolderNode;
  depth: number;
  selected: string;
  expanded: Set<string>;
  t: T;
  onToggle: (path: string) => void;
  onSelect: (node: FolderNode) => void;
}

function FolderTreeNode({ node, depth, selected, expanded, t, onToggle, onSelect }: FolderTreeNodeProps) {
  const hasChildren = node.children.length > 0;
  const isExpanded = expanded.has(node.path);
  const isSelected = selected === node.path;
  const FolderIcon = isExpanded ? FolderOpen : Folder;
  return <>
    <div className={`file-tree-row ${isSelected ? 'active' : ''}`} style={{ paddingLeft: `${6 + depth * 15}px` }} role="treeitem" aria-selected={isSelected} aria-expanded={hasChildren ? isExpanded : undefined}>
      {hasChildren
        ? <button className="file-tree-toggle" onClick={() => onToggle(node.path)} title={t(isExpanded ? 'collapse' : 'expand')} aria-label={t(isExpanded ? 'collapse' : 'expand')}>{isExpanded ? <ChevronDown /> : <ChevronRight />}</button>
        : <span className="file-tree-spacer" />}
      <button className="file-tree-label" onClick={() => onSelect(node)} title={node.path}><FolderIcon /><span>{node.name}</span></button>
    </div>
    {hasChildren && isExpanded && <div role="group">{node.children.map((child) => <FolderTreeNode key={child.path} node={child} depth={depth + 1} selected={selected} expanded={expanded} t={t} onToggle={onToggle} onSelect={onSelect} />)}</div>}
  </>;
}

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
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(() => new Set());
  const [mediaPage, setMediaPage] = useState(1);
  const mediaTableRef = useRef<HTMLDivElement>(null);
  const breadcrumbRef = useRef<HTMLElement>(null);
  const mediaPageSize = 30;
  const mediaFiles = (library?.files || []).filter((file) => file.playable && (file.media_type === 'video' || file.media_type === 'audio') && directParent(file.relative_path) === folder);
  const mediaPages = Math.max(1, Math.ceil((library?.total || 0) / mediaPageSize));
  const normalizedMediaPage = Math.min(mediaPages, Math.max(1, mediaPage));
  const mediaPageItems = paginationItems(normalizedMediaPage, mediaPages);
  const folderItems = library?.folders || [];
  const folderTree = buildFolderTree(folderItems);
  const breadcrumbParts = folder.split('/').filter(Boolean);
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
  function toggleFolder(path: string) {
    setExpandedFolders((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }
  function selectFolder(node: FolderNode) {
    if (node.children.length) {
      setExpandedFolders((current) => new Set(current).add(node.path));
    }
    void changeFolder(node.path);
  }
  async function changeMediaPage(nextPage: number) {
    const page = Math.min(mediaPages, Math.max(1, nextPage));
    setMediaPage(page);
    await load((page - 1) * mediaPageSize);
    mediaTableRef.current?.scrollTo({ top: 0 });
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
  useEffect(() => {
    if (folder) {
      const parts = folder.split('/');
      setExpandedFolders((current) => {
        const next = new Set(current);
        for (let depth = 1; depth < parts.length; depth += 1) next.add(parts.slice(0, depth).join('/'));
        return next;
      });
    }
    window.requestAnimationFrame(() => breadcrumbRef.current?.scrollTo({ left: breadcrumbRef.current.scrollWidth }));
  }, [folder]);

  return <div className="file-browser-grid">
    <aside className="panel acrylic file-tree-panel">
      <div className="panel-header"><div><h2>{t('folderTree')}</h2><span>{folderItems.length} {t('folderFilter')}</span></div><button className="icon-button" disabled={!expandedFolders.size} onClick={() => setExpandedFolders(new Set())} title={t('collapse')} aria-label={t('collapse')}><ListCollapse /></button></div>
      <div className="file-tree-list" role="tree">
        <div className={`file-tree-row root ${folder === '' ? 'active' : ''}`} role="treeitem" aria-selected={folder === ''}><span className="file-tree-spacer" /><button className="file-tree-label" onClick={() => void changeFolder('')}><HardDrive /><span>{t('allFolders')}</span></button></div>
        {folderTree.map((node) => <FolderTreeNode key={node.path} node={node} depth={0} selected={folder} expanded={expandedFolders} t={t} onToggle={toggleFolder} onSelect={selectFolder} />)}
      </div>
    </aside>
    <section className="panel acrylic file-media-panel"><div className="panel-header"><div className="file-folder-heading"><h2>{t('mediaInFolder')}</h2><nav className="file-breadcrumb" aria-label={t('folderTree')} ref={breadcrumbRef}><button onClick={() => void changeFolder('')}><HardDrive /><span>{t('allFolders')}</span></button>{breadcrumbParts.map((part, index) => { const path = breadcrumbParts.slice(0, index + 1).join('/'); return <span key={path}><ChevronRight /><button className={path === folder ? 'current' : ''} onClick={() => void changeFolder(path)} title={path}>{part}</button></span>; })}</nav><span className="muted">{t('directMediaOnly')}</span></div><div className="toolbar file-toolbar-inline">
      <input value={query} placeholder={t('searchFiles')} onChange={(event) => setQuery(event.target.value)} />
      <button onClick={() => { setMediaPage(1); void load(0); }}>{t('search')}</button>
      <ManifestExport disabled={!folder} manifestUrl={manifestUrl} aria2Filename={aria2Filename} t={t} />
      <a className={`button-link ${folder ? '' : 'disabled'}`} href={folderUrl} aria-disabled={!folder} onClick={(event) => { if (!folder) event.preventDefault(); }}>{t('downloadFolder')}</a>
      <button className="danger" disabled={!folder} onClick={() => void removeFolder()}>{t('deleteFolder')}</button>
    </div></div><div className="panel-body media-table-body">
      {!mediaFiles.length && <div className="empty-state">{t('noFiles')}</div>}
      {!!mediaFiles.length && <div className="media-table-wrap" ref={mediaTableRef}><table className="media-table"><thead><tr><th>{t('title')}</th><th>{t('type')}</th><th>{t('size')}</th><th></th></tr></thead><tbody>{mediaFiles.map((file) => <tr key={file.id}><td><strong>{file.name}</strong></td><td><span className="badge green">{mediaLabel(file.media_type, t)}</span></td><td>{formatBytes(file.size)}</td><td><div className="toolbar compact-actions"><button onClick={() => onPlay(file, mediaFiles, folder)}>{t('play')}</button><a className="button-link" href={withAuthUrl(file.download_url, token)}>{t('download')}</a><button onClick={() => navigator.clipboard?.writeText(withAuthUrl(file.download_url, token))}>{t('copyLink')}</button><button className="danger" onClick={() => void removeFile(file)}>{t('deleteFile')}</button></div></td></tr>)}</tbody></table></div>}
      <div className="pagination-row"><button onClick={() => void changeMediaPage(normalizedMediaPage - 1)} disabled={normalizedMediaPage <= 1}>{t('previousPage')}</button><span className="muted">{formatPageInfo(t('pageInfo'), normalizedMediaPage, mediaPages, library?.total || 0)}</span><div className="page-list" aria-label="Pagination">{mediaPageItems.map((item, index) => item === 'ellipsis' ? <span className="page-ellipsis" key={`ellipsis-${index}`}>...</span> : <button className={item === normalizedMediaPage ? 'active' : ''} key={item} onClick={() => void changeMediaPage(item)} disabled={item === normalizedMediaPage} aria-current={item === normalizedMediaPage ? 'page' : undefined}>{item}</button>)}</div><button onClick={() => void changeMediaPage(normalizedMediaPage + 1)} disabled={normalizedMediaPage >= mediaPages}>{t('nextPage')}</button></div>
    </div></section>
  </div>;
}
