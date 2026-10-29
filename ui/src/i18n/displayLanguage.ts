/** Endonyms and short codes the UI stores. Display names follow the UI language. */
const ENDONYMS: Record<string, string> = {
  english: 'en',
  español: 'es',
  espanol: 'es',
  spanish: 'es',
  français: 'fr',
  francais: 'fr',
  french: 'fr',
  deutsch: 'de',
  german: 'de',
  italiano: 'it',
  italian: 'it',
  português: 'pt',
  portugues: 'pt',
  portuguese: 'pt',
  català: 'ca',
  catala: 'ca',
  catalan: 'ca',
  中文: 'zh',
  chinese: 'zh',
  日本語: 'ja',
  japanese: 'ja',
  한국어: 'ko',
  korean: 'ko',
  العربية: 'ar',
  arabic: 'ar',
  हिन्दी: 'hi',
  hindi: 'hi',
  русский: 'ru',
  russian: 'ru',
}

/** Name of a stored language endonym in the current UI language. Unknown text stays as stored. */
export function displayLanguageName(stored: string, uiLanguage: string): string {
  const trimmed = stored.trim()
  if (!trimmed) return trimmed
  const code = ENDONYMS[trimmed.toLowerCase()]
    || (/^[a-z]{2,3}(?:-[a-z0-9]+)?$/i.test(trimmed) ? trimmed : '')
  if (!code) return trimmed
  try {
    return new Intl.DisplayNames([uiLanguage || 'en'], { type: 'language' }).of(code) || trimmed
  } catch {
    return trimmed
  }
}
