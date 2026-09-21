import { detectUiLanguage } from '../../i18n/language'
import en from './locales/en.json' with { type: 'json' }
import es from './locales/es.json' with { type: 'json' }

export type ReviewCopy = typeof en

export function reviewCopy(language = detectUiLanguage()): ReviewCopy {
  return language === 'es' ? es : en
}

export function interpolate(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{\{(\w+)\}\}/g, (_, key: string) => String(values[key] ?? ''))
}

export function catalogKeys(value: unknown, prefix = ''): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return prefix ? [prefix] : []
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) => (
    catalogKeys(child, prefix ? `${prefix}.${key}` : key)
  ))
}

export function localeKeyParity(): string[] {
  const enKeys = new Set(catalogKeys(en))
  const esKeys = new Set(catalogKeys(es))
  const missing: string[] = []
  for (const key of enKeys) if (!esKeys.has(key)) missing.push(`es: ${key}`)
  for (const key of esKeys) if (!enKeys.has(key)) missing.push(`en: ${key}`)
  return missing
}
