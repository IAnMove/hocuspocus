import { detectUiLanguage } from '../../i18n/language.ts'
import en from './locales/en.json' with { type: 'json' }
import es from './locales/es.json' with { type: 'json' }

export type DiagnosticsCopy = typeof en

export function diagnosticsCopy(language = detectUiLanguage()): DiagnosticsCopy {
  return language === 'es' ? es : en
}
