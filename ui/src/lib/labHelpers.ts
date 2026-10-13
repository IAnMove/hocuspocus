import i18n from '../i18n'
import { contentLanguageForUi, scaffoldLanguage } from './contentLanguage'

export interface CreativeCharacter {
  name: string
  role: string
  personality: string
  desire: string
  flaw: string
  appearance: string
  voice: string
}

export interface CreativeLocation {
  name: string
  purpose: string
  description: string
}

export const normalizeName = (value: string): string => value
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/[^a-zA-Z0-9]+/g, ' ')
  .trim()
  .toLowerCase()

export const boundedDuration = (value: number | undefined, fallback: number): number => (
  Math.max(15, Math.min(3_600, Math.round(value || fallback)))
)

export const explicitMusicLanguage = (value: string): string => {
  const raw = value.trim()
  const aliases: Record<string, string> = {
    es: 'Español', en: 'English', fr: 'Français', de: 'Deutsch',
    it: 'Italiano', pt: 'Português', ja: '日本語', ko: '한국어', zh: '中文',
  }
  return aliases[raw.toLowerCase()] || raw || contentLanguageForUi().language
}

export function creativeCharacters(values: CreativeCharacter[], language?: string): CreativeCharacter[] {
  if (values.length) return values
  const lng = scaffoldLanguage(language)
  return [{
    name: i18n.t('storyLab:scaffold.roleLead', { lng }),
    role: i18n.t('storyLab:scaffold.roleLead', { lng }),
    personality: i18n.t('storyLab:scaffold.personality', { lng }),
    desire: i18n.t('storyLab:scaffold.desire', { lng }),
    flaw: i18n.t('storyLab:scaffold.flaw', { lng }),
    appearance: i18n.t('storyLab:scaffold.appearance', { lng }),
    voice: i18n.t('storyLab:scaffold.voice', { lng }),
  }]
}

export function creativeLocations(values: CreativeLocation[], language?: string): CreativeLocation[] {
  if (values.length) return values
  const lng = scaffoldLanguage(language)
  return [{
    name: i18n.t('storyLab:scaffold.locationMain', { lng }),
    purpose: i18n.t('storyLab:scaffold.locationPurpose', { lng }),
    description: i18n.t('storyLab:scaffold.locationDescription', { lng }),
  }]
}

/**
 * The Wizard does not block on questions, so it creates Stories and Series with
 * whatever the user left out, and it must not invent a look to fill the gap.
 * This is the one deterministic reply line that says what stayed unset ("" when
 * the user gave everything). Interface language, like the rest of the reply.
 */
export function unsetDefaultsLine(unset: { style: boolean; tone: boolean }): string {
  const list = [
    unset.style ? i18n.t('wizard:styleUnset') : '',
    unset.tone ? i18n.t('wizard:toneUnset') : '',
  ].filter(Boolean).join(', ')
  return list ? i18n.t('wizard:defaultsChosen', { list }) : ''
}

export function outlineBeats(values: string[], premise: string, ending: string, language?: string): string[] {
  if (values.length >= 3) return values
  const lng = scaffoldLanguage(language)
  return [
    i18n.t('storyLab:scaffold.beatOpening', {
      lng,
      premise: premise || i18n.t('storyLab:scaffold.premiseFallback', { lng }),
    }),
    i18n.t('storyLab:scaffold.beatMiddle', { lng }),
    i18n.t('storyLab:scaffold.beatEnding', {
      lng,
      ending: ending || i18n.t('storyLab:scaffold.endingFallback', { lng }),
    }),
  ]
}


