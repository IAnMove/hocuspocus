import commonEn from './locales/en/common.json'
import navigationEn from './locales/en/navigation.json'
import settingsEn from './locales/en/settings.json'
import wizardEn from './locales/en/wizard.json'
import activityEn from './locales/en/activity.json'
import extraInfoEn from './locales/en/extraInfo.json'
import storyLabEn from './locales/en/storyLab.json'
import directorEn from './locales/en/director.json'
import seriesLabEn from './locales/en/seriesLab.json'
import videoEditorEn from './locales/en/videoEditor.json'
import workspacesEn from './locales/en/workspaces.json'
import styleSheetEn from './locales/en/styleSheet.json'
import projectsEn from './locales/en/projects.json'
import auditDevEn from './locales/en/auditDev.json'
import commonEs from './locales/es/common.json'
import navigationEs from './locales/es/navigation.json'
import settingsEs from './locales/es/settings.json'
import wizardEs from './locales/es/wizard.json'
import activityEs from './locales/es/activity.json'
import extraInfoEs from './locales/es/extraInfo.json'
import storyLabEs from './locales/es/storyLab.json'
import directorEs from './locales/es/director.json'
import seriesLabEs from './locales/es/seriesLab.json'
import videoEditorEs from './locales/es/videoEditor.json'
import workspacesEs from './locales/es/workspaces.json'
import styleSheetEs from './locales/es/styleSheet.json'
import projectsEs from './locales/es/projects.json'
import auditDevEs from './locales/es/auditDev.json'

export const NAMESPACES = ['common', 'navigation', 'settings', 'wizard', 'activity', 'extraInfo', 'storyLab', 'director', 'seriesLab', 'videoEditor', 'workspaces', 'styleSheet', 'projects', 'auditDev'] as const
export type I18nNamespace = (typeof NAMESPACES)[number]

export const resources = {
  en: {
    common: commonEn,
    navigation: navigationEn,
    settings: settingsEn,
    wizard: wizardEn,
    activity: activityEn,
    extraInfo: extraInfoEn,
    storyLab: storyLabEn,
    director: directorEn,
    seriesLab: seriesLabEn,
    videoEditor: videoEditorEn,
    workspaces: workspacesEn,
    styleSheet: styleSheetEn,
    projects: projectsEn,
    auditDev: auditDevEn,
  },
  es: {
    common: commonEs,
    navigation: navigationEs,
    settings: settingsEs,
    wizard: wizardEs,
    activity: activityEs,
    extraInfo: extraInfoEs,
    storyLab: storyLabEs,
    director: directorEs,
    seriesLab: seriesLabEs,
    videoEditor: videoEditorEs,
    workspaces: workspacesEs,
    styleSheet: styleSheetEs,
    projects: projectsEs,
    auditDev: auditDevEs,
  },
} as const

export type UiLanguage = keyof typeof resources
export const UI_LANGUAGES: UiLanguage[] = ['en', 'es']
export const DEFAULT_LANGUAGE: UiLanguage = 'en'
