import i18n from 'i18next'
import { initReactI18next, useTranslation } from 'react-i18next'
import { detectUiLanguage, persistUiLanguage } from './language'
import { DEFAULT_LANGUAGE, NAMESPACES, resources, type UiLanguage } from './resources'

export { LANGUAGE_STORAGE_KEY, detectUiLanguage, isUiLanguage, persistUiLanguage } from './language'
export { DEFAULT_LANGUAGE, NAMESPACES, UI_LANGUAGES, resources, type UiLanguage } from './resources'

let started = false

const INIT_OPTIONS = {
  resources,
  fallbackLng: DEFAULT_LANGUAGE,
  defaultNS: 'common' as const,
  ns: [...NAMESPACES],
  interpolation: { escapeValue: false },
  returnNull: false,
  returnEmptyString: false,
  react: { useSuspense: false },
}

export function createUiI18n(language: UiLanguage = detectUiLanguage()) {
  const instance = i18n.createInstance()
  void instance.use(initReactI18next).init({
    ...INIT_OPTIONS,
    lng: language,
  })
  persistUiLanguage(language)
  return instance
}

export function ensureUiI18n() {
  if (!started) {
    const language = detectUiLanguage()
    void i18n.use(initReactI18next).init({
      ...INIT_OPTIONS,
      lng: language,
    })
    persistUiLanguage(language)
    started = true
  }
  return i18n
}

export const useUiTranslation: typeof useTranslation = ((...args) => {
  ensureUiI18n()
  return useTranslation(...args)
}) as typeof useTranslation

export async function setUiLanguage(language: UiLanguage): Promise<void> {
  const instance = ensureUiI18n()
  await instance.changeLanguage(language)
  persistUiLanguage(language)
}

const i18nSingleton = ensureUiI18n()
export default i18nSingleton
