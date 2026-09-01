import type { AnalyzeResponse, DownloadMode, FormatInfo, PlaylistEntry } from '../../api/types';

export function playlistItemsValue(selectedIndexes: number[], total?: number | null): string | null {
  if (!selectedIndexes.length) return null;
  const sorted = [...new Set(selectedIndexes)].sort((a, b) => a - b);
  if (total && sorted.length === total && sorted[0] === 1 && sorted[sorted.length - 1] === total) return null;
  const ranges: string[] = [];
  let start = sorted[0];
  let previous = sorted[0];
  for (const index of sorted.slice(1)) {
    if (index === previous + 1) {
      previous = index;
      continue;
    }
    ranges.push(start === previous ? String(start) : `${start}-${previous}`);
    start = index;
    previous = index;
  }
  ranges.push(start === previous ? String(start) : `${start}-${previous}`);
  return ranges.join(',');
}

export function selectedPlaylistEntries(analysis: AnalyzeResponse | null, selectedIndexes: number[]): PlaylistEntry[] {
  if (!analysis?.playlist_entries.length) return [];
  const selected = new Set(selectedIndexes);
  return analysis.playlist_entries.filter((entry) => selected.has(entry.index));
}

export function taskFilenameTemplate(baseTemplate: string, isPlaylist: boolean): string {
  if (!isPlaylist) return baseTemplate;
  if (baseTemplate.includes('%(playlist_title)') || baseTemplate.includes('%(playlist_index)')) return baseTemplate;
  return `%(playlist_title)s/%(playlist_index)02d-${baseTemplate}`;
}

export function modeFormats(formats: FormatInfo[], mode: DownloadMode): FormatInfo[] {
  if (mode === 'audio') {
    const audioFormats = formats.filter((format) => format.type === 'audio' || format.format_id === 'bestaudio');
    return audioFormats.length ? audioFormats : formats.filter((format) => format.audio_codec && format.audio_codec !== 'none');
  }
  if (mode === 'video') {
    const videoFormats = formats.filter((format) => format.type === 'video+audio' || format.type === 'video' || format.format_id === 'best');
    return videoFormats.length ? videoFormats : formats;
  }
  return [];
}

export function preferredFormatForMode(formats: FormatInfo[], mode: DownloadMode, defaultResolution = 'best'): string | null {
  if (mode === 'subtitles') return null;
  const candidates = modeFormats(formats, mode);
  if (mode === 'audio') return candidates.find((format) => format.format_id === 'bestaudio')?.format_id || candidates[0]?.format_id || null;
  if (defaultResolution !== 'best') {
    const resolutionNumber = Number(defaultResolution.replace(/p$/i, ''));
    const matched = candidates.find((format) => {
      const text = [format.resolution, format.format_id].filter(Boolean).join(' ');
      return text.includes(defaultResolution) || text.includes(String(resolutionNumber));
    });
    if (matched) return matched.format_id;
  }
  return candidates.find((format) => format.format_id === 'best')?.format_id || candidates[0]?.format_id || null;
}

export function formatLabel(format: FormatInfo): string {
  return [format.format_id, format.type, format.resolution, format.ext, format.video_codec, format.audio_codec].filter(Boolean).map(String).join(' / ');
}

export function toggleListItem(list: string[], item: string): string[] {
  return list.includes(item) ? list.filter((value) => value !== item) : [...list, item].sort();
}

export function rawText(analysis: AnalyzeResponse, key: string): string | null {
  const value = analysis.raw?.[key];
  return typeof value === 'string' && value ? value : null;
}
