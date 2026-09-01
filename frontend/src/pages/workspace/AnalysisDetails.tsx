import { useEffect, useState } from 'react';
import type { AnalyzeResponse, DownloadMode, FormatInfo, PlaylistEntry } from '../../api/types';
import type { T } from '../../i18n';
import { formatBytes, formatPageInfo } from '../../shared/format';
import { paginationItems } from '../../shared/pagination';
import { modeFormats } from './workspaceUtils';

interface AnalysisDetailsProps {
  analysis: AnalyzeResponse | null;
  mode: DownloadMode;
  selectedPlaylistIndexes: number[];
  selectedFormat: string | null;
  onPlaylistSelected: (indexes: number[]) => void;
  onFormatSelected: (id: string) => void;
  t: T;
}

export function AnalysisDetails(props: AnalysisDetailsProps) {
  const { analysis, mode, selectedPlaylistIndexes, selectedFormat, onPlaylistSelected, onFormatSelected, t } = props;
  const hasPlaylist = Boolean(analysis?.playlist_entries.length);
  const [tab, setTab] = useState<'playlist' | 'formats'>('formats');
  useEffect(() => setTab(hasPlaylist ? 'playlist' : 'formats'), [analysis?.url, hasPlaylist]);
  if (!analysis) return null;
  return <div className="section-block analysis-details">
    <div className="segmented compact-segmented"><button className={tab === 'playlist' ? 'active' : ''} disabled={!hasPlaylist} onClick={() => setTab('playlist')}>{t('analysisPlaylistTab')} {hasPlaylist ? `(${analysis.playlist_entries.length})` : ''}</button><button className={tab === 'formats' ? 'active' : ''} onClick={() => setTab('formats')}>{t('analysisFormatsTab')} ({analysis.formats.length})</button></div>
    {tab === 'playlist' && <PlaylistTable entries={analysis.playlist_entries} selected={selectedPlaylistIndexes} onSelected={onPlaylistSelected} t={t} />}
    {tab === 'formats' && <FormatTable formats={modeFormats(analysis.formats, mode)} selected={selectedFormat} onSelected={onFormatSelected} t={t} />}
  </div>;
}

function PlaylistTable({ entries, selected, onSelected, t }: { entries: PlaylistEntry[]; selected: number[]; onSelected: (indexes: number[]) => void; t: T }) {
  const [page, setPage] = useState(0);
  const pageSize = 10;
  const pageCount = Math.max(1, Math.ceil(entries.length / pageSize));
  const pageItems = paginationItems(page + 1, pageCount);
  useEffect(() => setPage(0), [entries]);
  if (!entries.length) return null;
  const pageEntries = entries.slice(page * pageSize, page * pageSize + pageSize);
  const selectedSet = new Set(selected);
  const allSelected = selected.length === entries.length;
  function toggle(index: number) {
    if (selectedSet.has(index)) onSelected(selected.filter((item) => item !== index));
    else onSelected([...selected, index].sort((a, b) => a - b));
  }
  return <div className="section-block">
    <div className="section-heading"><h2>{t('playlistSelection')}</h2><div className="toolbar"><span className="badge blue">{selected.length} {t('selectedItemsCount')}</span><span className="badge">{formatPageInfo(t('pageInfo'), page + 1, pageCount, entries.length)}</span><button onClick={() => setPage(Math.max(0, page - 1))} disabled={page <= 0}>{t('previousPage')}</button><div className="page-list compact-page-list" aria-label="Pagination">{pageItems.map((item, index) => item === 'ellipsis' ? <span className="page-ellipsis" key={`playlist-ellipsis-${index}`}>...</span> : <button className={item === page + 1 ? 'active' : ''} key={item} onClick={() => setPage(item - 1)} disabled={item === page + 1} aria-current={item === page + 1 ? 'page' : undefined}>{item}</button>)}</div><button onClick={() => setPage(Math.min(pageCount - 1, page + 1))} disabled={page >= pageCount - 1}>{t('nextPage')}</button><button onClick={() => onSelected(entries.map((entry) => entry.index))} disabled={allSelected}>{t('allItems')}</button><button onClick={() => onSelected([])} disabled={!selected.length}>{t('clearItems')}</button></div></div>
    <div className="table-wrap playlist-wrap"><table><thead><tr><th>{t('pick')}</th><th>{t('playlistIndex')}</th><th>{t('title')}</th><th>{t('channel')}</th><th>{t('duration')}</th></tr></thead><tbody>{pageEntries.map((entry) => <tr key={entry.index} className={selectedSet.has(entry.index) ? 'selected' : ''} onClick={() => toggle(entry.index)}><td><input type="checkbox" checked={selectedSet.has(entry.index)} onChange={() => toggle(entry.index)} onClick={(event) => event.stopPropagation()} /></td><td>{entry.index}</td><td><strong>{entry.title || entry.id || entry.url || '-'}</strong></td><td>{entry.channel || '-'}</td><td>{entry.duration ? `${Math.round(entry.duration / 60)} ${t('minutes')}` : '-'}</td></tr>)}</tbody></table></div>
  </div>;
}

function FormatTable({ formats, selected, onSelected, t }: { formats: FormatInfo[]; selected: string | null; onSelected: (id: string) => void; t: T }) {
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const pageCount = Math.max(1, Math.ceil(formats.length / pageSize));
  useEffect(() => setPage(0), [formats]);
  if (!formats.length) return null;
  const pageFormats = formats.slice(page * pageSize, page * pageSize + pageSize);
  return <div className="section-block"><div className="section-heading"><h2>{t('analysisFormatsTab')}</h2><div className="toolbar"><span className="badge">{formatPageInfo(t('pageInfo'), page + 1, pageCount, formats.length)}</span><button onClick={() => setPage(Math.max(0, page - 1))} disabled={page <= 0}>{t('previousPage')}</button><button onClick={() => setPage(Math.min(pageCount - 1, page + 1))} disabled={page >= pageCount - 1}>{t('nextPage')}</button></div></div><div className="table-wrap"><table><thead><tr><th>{t('pick')}</th><th>{t('type')}</th><th>{t('resolution')}</th><th>{t('ext')}</th><th>{t('video')}</th><th>{t('audio')}</th><th>{t('fps')}</th><th>{t('size')}</th><th>{t('id')}</th></tr></thead><tbody>{pageFormats.map((format) => <tr key={format.format_id} className={selected === format.format_id ? 'selected' : ''} onClick={() => onSelected(format.format_id)}><td><input type="radio" checked={selected === format.format_id} onChange={() => onSelected(format.format_id)} /></td><td>{format.type}</td><td>{format.resolution || '-'}</td><td>{format.ext || '-'}</td><td>{format.video_codec || '-'}</td><td>{format.audio_codec || '-'}</td><td>{format.fps || '-'}</td><td>{formatBytes(format.filesize)}</td><td>{format.format_id}</td></tr>)}</tbody></table></div></div>;
}
