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
  // Fresh installs start in English; an explicit saved choice always wins.
  return DEFAULT_LANGUAGE
}

export function persistUiLanguage(language: UiLanguage): void {
  safeStorageSet('local', LANGUAGE_STORAGE_KEY, language)
  if (typeof document !== 'undefined') document.documentElement.lang = language
}
