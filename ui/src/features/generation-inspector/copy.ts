import { detectUiLanguage } from '../../i18n/language'
import en from '../../i18n/locales/en/generationInspector.json' with { type: 'json' }
import es from '../../i18n/locales/es/generationInspector.json' with { type: 'json' }

export type InspectorCopy = typeof en

export function inspectorCopy(language = detectUiLanguage()): InspectorCopy {
  return language === 'es' ? es : en
}

export function interpolate(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{\{(\w+)\}\}/g, (_, key: string) => String(values[key] ?? ''))
}
