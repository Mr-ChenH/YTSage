import type { FileEntry } from '../api/types';
import type { T } from '../i18n';
import { formatBytes, mediaLabel } from './format';

export function fileDirectory(file: FileEntry): string {
  const normalized = file.relative_path.replaceAll('\\', '/');
  const suffix = `/${file.name}`;
  if (normalized === file.name) return '';
  if (normalized.endsWith(suffix)) return normalized.slice(0, -suffix.length);
  const index = normalized.lastIndexOf('/');
  return index >= 0 ? normalized.slice(0, index) : '';
}

export function playlistMeta(file: FileEntry, t: T): string {
  const directory = fileDirectory(file);
  return directory ? `${directory} - ${formatBytes(file.size)}` : `${mediaLabel(file.media_type, t)} - ${formatBytes(file.size)}`;
}

export function directParent(relativePath: string): string {
  const normalized = relativePath.replaceAll('\\', '/');
  const index = normalized.lastIndexOf('/');
  return index >= 0 ? normalized.slice(0, index) : '';
}

export function withAuthUrl(url: string | null | undefined, token: string): string {
  if (!url) return '#';
  return `${url}${token ? `?token=${encodeURIComponent(token)}` : ''}`;
}
