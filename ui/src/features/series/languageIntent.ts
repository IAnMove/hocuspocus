import { mergeLanguageIntent, type LanguageIntent } from '../../lib/languageIntent'
import type { SeriesProject } from './types'

export function resolveSeriesLanguageIntent(
  series: SeriesProject,
  legacyLanguage: string,
  update: LanguageIntent | undefined,
): LanguageIntent {
  const merged = mergeLanguageIntent(series.languageIntent, update, {
    contentLanguage: series.language,
    spokenLanguage: series.spokenLanguage,
    technicalPromptLanguage: 'en',
  })
  if (!legacyLanguage) return merged
  return {
    ...merged,
    contentLanguage: update?.contentLanguage || legacyLanguage,
    spokenLanguage: update?.spokenLanguage || legacyLanguage,
  }
}

export function seriesLanguageIntentAffectsCanon(
  series: SeriesProject,
  next: LanguageIntent,
): boolean {
  const current = series.languageIntent
  return next.contentLanguage !== current.contentLanguage
    || next.spokenLanguage !== current.spokenLanguage
    || next.technicalPromptLanguage !== current.technicalPromptLanguage
    || JSON.stringify(next.verbatimSegments) !== JSON.stringify(current.verbatimSegments)
    || next.contentLanguage !== series.language
    || next.spokenLanguage !== series.spokenLanguage
}

export function seriesContentLanguagePatch(
  series: SeriesProject,
  language: string,
): Pick<SeriesProject, 'language' | 'languageIntent'> {
  return {
    language,
    languageIntent: { ...series.languageIntent, contentLanguage: language },
  }
}

export function seriesSpokenLanguagePatch(
  series: SeriesProject,
  spokenLanguage: string,
): Pick<SeriesProject, 'spokenLanguage' | 'languageIntent'> {
  return {
    spokenLanguage,
    languageIntent: { ...series.languageIntent, spokenLanguage },
  }
}
