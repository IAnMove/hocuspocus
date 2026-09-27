import { safeStorageGet, safeStorageSet } from '../lib/safeStorage'
import { DEFAULT_LANGUAGE, UI_LANGUAGES, type UiLanguage } from './resources'
import { LANGUAGE_STORAGE_KEY } from './storageKey'

export { LANGUAGE_STORAGE_KEY }

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

/** Content and spoken language that new projects start with, following the UI language. */
export function defaultProjectLanguages(): { content: string; spoken: string } {
  return detectUiLanguage() === 'es'
    ? { content: 'Español', spoken: 'Español de España' }
    : { content: 'English', spoken: 'English' }
}

export function persistUiLanguage(language: UiLanguage): void {
  safeStorageSet('local', LANGUAGE_STORAGE_KEY, language)
  if (typeof document !== 'undefined') document.documentElement.lang = language
}
