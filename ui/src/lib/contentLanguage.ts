import i18n from '../i18n'

/** Human labels stored on stories, series, and director sessions. */
export interface ContentLanguage {
  language: string
  spokenLanguage: string
  code: 'en' | 'es'
}

/**
 * Language for content created right now. Saved projects do not call this:
 * a missing field on an old file stays English so switching the UI later
 * does not rewrite it.
 */
export function contentLanguageForUi(language = i18n.resolvedLanguage || i18n.language): ContentLanguage {
  const spanish = String(language || 'en').toLowerCase().startsWith('es')
  return spanish
    ? { language: 'Español', spokenLanguage: 'Español de España', code: 'es' }
    : { language: 'English', spokenLanguage: 'English', code: 'en' }
}

/** Scaffold copy follows the content language being saved, not a later UI switch. */
export function scaffoldLanguage(language?: string | null): 'en' | 'es' {
  const raw = String(language || '').trim()
  if (!raw) return contentLanguageForUi().code
  const key = raw
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
  if (
    key.startsWith('es')
    || key.includes('espanol')
    || key.includes('castellano')
    || key.includes('spanish')
  ) return 'es'
  return 'en'
}
