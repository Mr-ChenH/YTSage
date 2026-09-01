import { useState } from 'react';
import type { T } from '../../i18n';

export type ManifestFormat = 'aria2' | 'txt' | 'json';

interface ManifestExportProps {
  disabled: boolean;
  manifestUrl: (format: ManifestFormat) => string;
  aria2Filename: string;
  t: T;
}

export function ManifestExport({ disabled, manifestUrl, aria2Filename, t }: ManifestExportProps) {
  const [format, setFormat] = useState<ManifestFormat>('aria2');
  const [copied, setCopied] = useState(false);
  const url = manifestUrl(format);
  async function copyCommand() {
    await navigator.clipboard?.writeText(`aria2c -d . -i "${aria2Filename}" --continue=true --split=8 --max-connection-per-server=8`);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  }
  return <div className="manifest-export">
    <select value={format} onChange={(event) => setFormat(event.target.value as ManifestFormat)} disabled={disabled} aria-label={t('manifestFormat')}>
      <option value="aria2">{t('manifestAria2')}</option>
      <option value="txt">{t('manifestTxt')}</option>
      <option value="json">{t('manifestJson')}</option>
    </select>
    <a className={`button-link ${disabled ? 'disabled' : ''}`} href={url} aria-disabled={disabled} onClick={(event) => { if (disabled) event.preventDefault(); }}>{t('exportManifest')}</a>
    <button disabled={disabled || format !== 'aria2'} onClick={() => void copyCommand()}>{copied ? t('copied') : t('copyAria2Command')}</button>
  </div>;
}
