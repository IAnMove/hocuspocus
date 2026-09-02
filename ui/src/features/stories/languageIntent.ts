import { mergeLanguageIntent, type LanguageIntent } from '../../lib/languageIntent'
import type { StoryProject } from './types'

export function applyStoryLanguageIntent(
  project: StoryProject,
  update: LanguageIntent | undefined,
  fallback: Partial<LanguageIntent> = {},
): StoryProject {
  if (!update && !Object.keys(fallback).length) return project
  const languageIntent = mergeLanguageIntent(project.languageIntent, update, {
    contentLanguage: project.language,
    spokenLanguage: project.spokenLanguage,
    ...fallback,
  })
  return {
    ...project,
    language: languageIntent.contentLanguage || project.language,
    spokenLanguage: languageIntent.spokenLanguage || project.spokenLanguage,
    languageIntent,
  }
}

export function seedStoryLanguageIntent(
  project: StoryProject,
  legacyLanguage: string,
  update: LanguageIntent | undefined,
): StoryProject {
  const languageIntent = mergeLanguageIntent(undefined, update, {
    contentLanguage: legacyLanguage || project.language,
    spokenLanguage: legacyLanguage || project.spokenLanguage,
    technicalPromptLanguage: 'en',
  })
  return {
    ...project,
    language: languageIntent.contentLanguage,
    spokenLanguage: languageIntent.spokenLanguage,
    languageIntent,
  }
}

export function applyLegacyStoryLanguage(
  project: StoryProject,
  language: string,
  explicitIntent: LanguageIntent | undefined,
): StoryProject {
  if (!language) return project
  const spokenLanguage = explicitIntent?.spokenLanguage || language
  return {
    ...project,
    language,
    spokenLanguage,
    languageIntent: {
      ...project.languageIntent,
      contentLanguage: language,
      spokenLanguage,
    },
  }
}
