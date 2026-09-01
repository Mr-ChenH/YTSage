import zhMessages from './zh.json';
import enMessages from './en.json';

export const messages = {
  zh: zhMessages,
  en: enMessages,
} as const satisfies Record<string, typeof zhMessages>;

export type Locale = keyof typeof messages;
export type TKey = keyof typeof messages.zh;
export type T = (key: TKey) => string;
