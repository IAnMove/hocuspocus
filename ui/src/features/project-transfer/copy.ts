import { detectUiLanguage } from '../../i18n/language'
import en from './locales/en.json' with { type: 'json' }
import es from './locales/es.json' with { type: 'json' }

export type TransferCopy = typeof en

export function transferCopy(language = detectUiLanguage()): TransferCopy {
  return language === 'es' ? es : en
}

export function interpolate(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{\{(\w+)\}\}/g, (_, key: string) => String(values[key] ?? ''))
}
