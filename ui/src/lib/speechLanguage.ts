/** Spoken-language labels ("Español de España", "English (US)", "es-ES") mapped to
 * the TTS language names and to the short codes lip-sync analysis expects. */
export const SPOKEN_LANGUAGES = ['english', 'spanish', 'french', 'german', 'italian', 'portuguese', 'japanese', 'korean', 'chinese', 'russian'] as const
export type SpokenLanguage = typeof SPOKEN_LANGUAGES[number]

const ALIASES: Record<SpokenLanguage, readonly string[]> = {
  english: ['en', 'english', 'inglés', 'ingles', 'anglais', 'englisch'],
  spanish: ['es', 'spanish', 'español', 'espanol', 'castellano', 'castilian'],
  french: ['fr', 'french', 'francés', 'frances', 'français', 'francais'],
  german: ['de', 'german', 'alemán', 'aleman', 'deutsch'],
  italian: ['it', 'italian', 'italiano'],
  portuguese: ['pt', 'portuguese', 'portugués', 'portugues', 'português'],
  japanese: ['ja', 'japanese', 'japonés', 'japones'],
  korean: ['ko', 'korean', 'coreano'],
  chinese: ['zh', 'cmn', 'chinese', 'chino', 'mandarin', 'mandarín'],
  russian: ['ru', 'russian', 'ruso'],
}
const ANALYSIS_CODE: Record<SpokenLanguage, string> = {
  english: 'en', spanish: 'es', french: 'fr', german: 'de', italian: 'it',
  portuguese: 'pt', japanese: 'ja', korean: 'ko', chinese: 'cmn', russian: 'ru',
}
const CODE = /^[a-z]{2,3}(?:[-_][a-z0-9]{2,4})?$/

export function spokenLanguage(raw: unknown): SpokenLanguage | undefined {
  if (typeof raw !== 'string') return undefined
  const head = raw.trim().toLocaleLowerCase().split(/[\s_\-(/,]+/)[0]
  return head ? SPOKEN_LANGUAGES.find(language => ALIASES[language].includes(head)) : undefined
}

/** Code for speech analysis: codes pass through, labels map to their code, anything else is auto (''). */
export function speechAnalysisLanguage(raw: unknown): string {
  if (typeof raw !== 'string') return ''
  const text = raw.trim().toLocaleLowerCase()
  if (CODE.test(text)) return text.replace('_', '-')
  const language = spokenLanguage(text)
  return language ? ANALYSIS_CODE[language] : ''
}
