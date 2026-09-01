import type { MediaType, TaskStatus } from '../api/types';
import type { T, TKey } from '../i18n';

export function formatBytes(value?: number | null): string {
  if (!value) return '-';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

export function formatPageInfo(template: string, page: number, pages: number, total: number): string {
  return template.replace('{page}', String(page)).replace('{pages}', String(pages)).replace('{total}', String(total));
}

export function statusTone(status?: string): string {
  if (status === 'completed') return 'green';
  if (status === 'running') return 'blue';
  if (status === 'queued') return 'amber';
  if (status === 'failed' || status === 'cancelled' || status === 'interrupted') return 'red';
  return '';
}

export function statusLabel(status: TaskStatus | string, t: T): string {
  const labels: Record<string, TKey> = {
    queued: 'statusQueued',
    running: 'statusRunning',
    completed: 'statusCompleted',
    failed: 'statusFailed',
    cancelled: 'statusCancelled',
    interrupted: 'statusInterrupted',
  };
  return labels[status] ? t(labels[status]) : status;
}

export function mediaLabel(mediaType: MediaType, t: T): string {
  const labels: Record<MediaType, TKey> = {
    video: 'mediaVideo',
    audio: 'mediaAudio',
    subtitle: 'mediaSubtitle',
    other: 'mediaOther',
  };
  return t(labels[mediaType]);
}
