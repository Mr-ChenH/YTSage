import type { ApiClient } from '../../api/client';
import type { TaskResponse } from '../../api/types';
import type { T } from '../../i18n';
import { statusLabel, statusTone } from '../../shared/format';
import { TaskPlaylist } from './TaskPlaylist';

interface TasksPageProps {
  tasks: TaskResponse[];
  api: ApiClient;
  t: T;
  onChanged: () => void;
  onCancel: (id: string) => Promise<void>;
}

export function TasksPage({ tasks, api, t, onChanged, onCancel }: TasksPageProps) {
  async function deleteTask(id: string) {
    await api.deleteTask(id);
    onChanged();
  }
  async function clearTasks() {
    if (!window.confirm(t('confirmClearTasks'))) return;
    await api.clearTasks();
    onChanged();
  }
  if (!tasks.length) return <div className="empty-state">{t('noTasks')}</div>;
  return <div className="stack"><div className="toolbar"><button onClick={() => void clearTasks()}>{t('clearRecords')}</button></div><div className="list">{tasks.map((task) => <div className="row" key={task.id}>
    <div className="row-top"><div className="stack"><strong>{String(task.options.url || task.url)}</strong><span className="muted">{task.progress.current_filename || task.output_path || task.id}</span></div><span className={`badge ${statusTone(task.status)}`}>{statusLabel(task.status, t)}</span></div>
    <TaskPlaylist task={task} api={api} t={t} onChanged={onChanged} />
    <div className="progress"><span style={{ width: `${Math.max(0, Math.min(100, task.progress.percent || 0))}%` }} /></div>
    <div className="row-top"><div className="toolbar"><span className="muted">{task.progress.status_text || '-'}</span>{task.status === 'running' && task.progress.speed && <span className="badge blue">{t('downloadSpeed')}: {task.progress.speed}</span>}{task.status === 'running' && task.progress.eta && <span className="badge">{t('eta')}: {task.progress.eta}</span>}</div><div className="toolbar">{['queued', 'running'].includes(task.status) && <button className="danger" onClick={() => void onCancel(task.id)}>{t('cancel')}</button>}<button onClick={() => void deleteTask(task.id)}>{t('deleteRecord')}</button></div></div>
    {task.error && <pre className="log-box">{task.error}</pre>}
  </div>)}</div></div>;
}
