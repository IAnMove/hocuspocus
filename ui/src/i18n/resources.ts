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
import scene3dEn from './locales/en/scene3d.json'
import shellEn from './locales/en/shell.json'
import charactersEn from './locales/en/characters.json'
import comicsEn from './locales/en/comics.json'
import studioEn from './locales/en/studio.json'
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
import scene3dEs from './locales/es/scene3d.json'
import shellEs from './locales/es/shell.json'
import charactersEs from './locales/es/characters.json'
import comicsEs from './locales/es/comics.json'
import studioEs from './locales/es/studio.json'

export const NAMESPACES = ['common', 'navigation', 'settings', 'wizard', 'activity', 'extraInfo', 'storyLab', 'director', 'seriesLab', 'videoEditor', 'workspaces', 'styleSheet', 'projects', 'auditDev', 'scene3d', 'shell', 'characters', 'comics', 'studio'] as const
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
    scene3d: scene3dEn,
    shell: shellEn,
    characters: charactersEn,
    comics: comicsEn,
    studio: studioEn,
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
    scene3d: scene3dEs,
    shell: shellEs,
    characters: charactersEs,
    comics: comicsEs,
    studio: studioEs,
  },
} as const

export type UiLanguage = keyof typeof resources
export const UI_LANGUAGES: UiLanguage[] = ['en', 'es']
export const DEFAULT_LANGUAGE: UiLanguage = 'en'
