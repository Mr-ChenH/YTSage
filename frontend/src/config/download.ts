import type { TKey } from '../i18n';

export const filenameTemplatePresets: Array<{ id: string; template: string; descKey: TKey }> = [
  { id: 'title', template: '%(title)s.%(ext)s', descKey: 'filenameTemplateDescTitle' },
  { id: 'title-id', template: '%(title)s_[%(id)s].%(ext)s', descKey: 'filenameTemplateDescTitleId' },
  { id: 'title-resolution-id', template: '%(title)s_%(resolution)s_[%(id)s].%(ext)s', descKey: 'filenameTemplateDescResolutionId' },
  { id: 'date-title-id', template: '%(upload_date)s_%(title)s_[%(id)s].%(ext)s', descKey: 'filenameTemplateDescDateTitleId' },
  { id: 'uploader-title-id', template: '%(uploader)s/%(title)s_[%(id)s].%(ext)s', descKey: 'filenameTemplateDescUploaderTitleId' },
];

export const videoResolutionOptions = ['best', '2160p', '1440p', '1080p', '720p', '480p', '360p'];
