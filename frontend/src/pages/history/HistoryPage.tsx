import type { ApiClient } from '../../api/client';
import type { HistoryEntry } from '../../api/types';
import type { T } from '../../i18n';
import { formatBytes, mediaLabel, statusLabel, statusTone } from '../../shared/format';

interface HistoryPageProps {
  entries: HistoryEntry[];
  api: ApiClient;
  t: T;
  onChanged: () => void;
  onOpenFiles: () => void;
}

export function HistoryPage({ entries, api, t, onChanged, onOpenFiles }: HistoryPageProps) {
  async function deleteHistory(id: string) {
    await api.deleteHistory(id);
    onChanged();
  }
  async function clearHistory() {
    if (!window.confirm(t('confirmClearHistory'))) return;
    await api.clearHistory();
    onChanged();
  }
  if (!entries.length) return <div className="empty-state">{t('noHistory')}</div>;
  return <div className="stack"><div className="toolbar"><button onClick={() => void clearHistory()}>{t('clearRecords')}</button></div><div className="list">{entries.map((entry) => <div className="row" key={entry.id}>
    <div className="row-top"><div className="stack"><strong>{entry.title || entry.url || entry.id}</strong><span className="muted">{entry.downloaded_at} - {formatBytes(entry.file_size)} - {mediaLabel(entry.media_type, t)}</span></div><span className={`badge ${statusTone(entry.status)}`}>{statusLabel(entry.status, t)}</span></div>
    <div className="toolbar"><button onClick={onOpenFiles}>{t('openFiles')}</button><button disabled={!entry.url}>{t('redownload')}</button><button onClick={() => entry.output_path && navigator.clipboard?.writeText(entry.output_path)}>{t('copyPath')}</button><button onClick={() => void deleteHistory(entry.id)}>{t('deleteRecord')}</button></div>
  </div>)}</div></div>;
}
