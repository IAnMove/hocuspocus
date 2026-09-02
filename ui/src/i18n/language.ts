import { safeStorageGet, safeStorageSet } from '../lib/safeStorage'
import { DEFAULT_LANGUAGE, UI_LANGUAGES, type UiLanguage } from './resources'

export const LANGUAGE_STORAGE_KEY = 'hocuspocus-ui-language'

export function isUiLanguage(value: string | null | undefined): value is UiLanguage {
  return UI_LANGUAGES.includes(value as UiLanguage)
}

export function detectUiLanguage(): UiLanguage {
  const stored = safeStorageGet('local', LANGUAGE_STORAGE_KEY)
  if (isUiLanguage(stored)) return stored
  const browser = typeof navigator !== 'undefined' ? navigator.language : ''
  if (browser.toLowerCase().startsWith('es')) return 'es'
  return DEFAULT_LANGUAGE
}

export function persistUiLanguage(language: UiLanguage): void {
  safeStorageSet('local', LANGUAGE_STORAGE_KEY, language)
  if (typeof document !== 'undefined') document.documentElement.lang = language
}
