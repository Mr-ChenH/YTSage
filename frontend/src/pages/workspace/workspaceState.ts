import type { AnalyzeResponse, DownloadMode } from '../../api/types';

export interface WorkspaceState {
  url: string;
  analysis: AnalyzeResponse | null;
  selectedFormat: string | null;
  audioFormat: string;
  videoOutputFormat: string;
  selectedSubtitleLangs: string[];
  mergeSubtitles: boolean;
  saveThumbnail: boolean;
  saveDescription: boolean;
  embedChapters: boolean;
  audioNormalization: boolean;
  proxyUrl: string;
  concurrentFragments: number;
  selectedPlaylistIndexes: number[];
  mode: DownloadMode;
}

export const initialWorkspaceState: WorkspaceState = {
  url: '',
  analysis: null,
  selectedFormat: null,
  audioFormat: 'mp3',
  videoOutputFormat: 'mp4',
  selectedSubtitleLangs: [],
  mergeSubtitles: true,
  saveThumbnail: false,
  saveDescription: false,
  embedChapters: true,
  audioNormalization: false,
  proxyUrl: '',
  concurrentFragments: 4,
  selectedPlaylistIndexes: [],
  mode: 'video',
};
