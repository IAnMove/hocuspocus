import commonEn from './locales/en/common.json'
import navigationEn from './locales/en/navigation.json'
import settingsEn from './locales/en/settings.json'
import wizardEn from './locales/en/wizard.json'
import activityEn from './locales/en/activity.json'
import commonEs from './locales/es/common.json'
import navigationEs from './locales/es/navigation.json'
import settingsEs from './locales/es/settings.json'
import wizardEs from './locales/es/wizard.json'
import activityEs from './locales/es/activity.json'

export const NAMESPACES = ['common', 'navigation', 'settings', 'wizard', 'activity'] as const
export type I18nNamespace = (typeof NAMESPACES)[number]

export const resources = {
  en: {
    common: commonEn,
    navigation: navigationEn,
    settings: settingsEn,
    wizard: wizardEn,
    activity: activityEn,
  },
  es: {
    common: commonEs,
    navigation: navigationEs,
    settings: settingsEs,
    wizard: wizardEs,
    activity: activityEs,
  },
} as const

export type UiLanguage = keyof typeof resources
export const UI_LANGUAGES: UiLanguage[] = ['en', 'es']
export const DEFAULT_LANGUAGE: UiLanguage = 'en'
