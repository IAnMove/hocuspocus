/**
 * Provider-free lyric language guard. Mirrors app/services/lyrics_language.py.
 * Technical captions are out of scope; pass only sung lyrics.
 */

const SECTION_TAG = /\[(?:intro|verse|pre[ -]?chorus|chorus|post[ -]?chorus|interlude|bridge|transition|build[ -]?up|break|hook|inst|instrumental|solo|outro|start|end)(?:[^\]]*)\]/gi

const SCRIPT_RUNS: Record<string, RegExp> = {
  han: /[\u3400-\u9fff]+/g,
  arabic: /[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff]+/g,
  cyrillic: /[\u0400-\u04ff]+/g,
  hangul: /[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]+/g,
  kana: /[\u3040-\u30ff]+/g,
}

const ENGLISH_MARKERS = new Set([
  'the', 'and', 'that', 'this', 'with', 'from', 'through', 'night',
  'our', 'your', 'you', 'we', 'are', 'not', 'for', 'but', 'his', 'her',
  'they', 'their', 'have', 'was', 'were', 'will', 'would', 'could',
  'should', 'fight', 'sing', 'server', 'software', 'proprietary',
])

const SPANISH_MARKERS = new Set([
  'el', 'la', 'los', 'las', 'que', 'de', 'del', 'en', 'y', 'un', 'una',
  'por', 'para', 'con', 'no', 'se', 'es', 'mi', 'tu', 'yo', 'somos',
  'noche', 'canta', 'cantar', 'esta', 'como', 'pero', 'porque',
])

export interface ProtectedLyricSegment {
  kind?: string
  text: string
  language?: string
}

export interface LyricsLanguageReport {
  ok: boolean
  lyrics: string
  repaired: boolean
  reasons: string[]
  languageMismatch: boolean
  strippedSpans: { script: string; text: string }[]
}

const LANGUAGE_ALIASES: Record<string, string> = {
  es: 'es', espanol: 'es', castellano: 'es',
  spanish: 'es', 'es-es': 'es', 'es-mx': 'es',
  en: 'en', english: 'en', ingles: 'en',
}

function folded(value: string): string {
  return value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase().trim()
}

export function canonicalLyricsLanguage(value: string): string {
  const key = folded(value)
  const exact = LANGUAGE_ALIASES[key] || LANGUAGE_ALIASES[key.split('-')[0]] || ''
  if (exact) return exact
  // Story Lab names such as "Español de España" are not exact aliases.
  // Skip 2-letter tokens so "en español" does not become English.
  for (const token of key.match(/[a-z]+/g) || []) {
    const mapped = LANGUAGE_ALIASES[token]
    if (mapped && token.length > 2) return mapped
  }
  return ''
}

function protectedTexts(segments: readonly ProtectedLyricSegment[] | undefined): string[] {
  return (segments || [])
    .filter(item => item?.text?.trim() && (!item.kind || ['lyrics', 'dialogue', 'visible_text', 'subtitle'].includes(item.kind)))
    .map(item => item.text)
}

function maskProtected(lyrics: string, literals: string[]): string {
  return literals.reduce((source, text, index) => (
    text && source.includes(text) ? source.split(text).join(`{{PROTECTED_${index}}}`) : source
  ), lyrics)
}

function restoreProtected(lyrics: string, literals: string[]): string {
  return lyrics.replace(/\{\{PROTECTED_(\d+)\}\}/g, (_match, raw) => {
    const index = Number(raw)
    return literals[index] ?? `{{PROTECTED_${raw}}}`
  })
}

function stripTags(lyrics: string): string {
  return lyrics.replace(SECTION_TAG, ' ')
}

function latinWords(sample: string): string[] {
  return sample.match(/[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+/g) || []
}

function scriptHits(sample: string): Record<string, string[]> {
  return Object.fromEntries(Object.entries(SCRIPT_RUNS).map(([name, pattern]) => [
    name,
    sample.match(new RegExp(pattern.source, 'g')) || [],
  ]))
}

function englishLineContamination(sample: string): boolean {
  return sample.split('\n').some(raw => {
    const words = latinWords(stripTags(raw).trim()).map(word => word.toLocaleLowerCase())
    if (words.length < 5) return false
    const english = words.filter(word => ENGLISH_MARKERS.has(word)).length
    const spanish = words.filter(word => SPANISH_MARKERS.has(word)).length
    return english >= 3 && english > spanish + 1 && english / words.length >= 0.35
  })
}

function spanishMismatch(sample: string): { mismatch: boolean; reasons: string[] } {
  const reasons: string[] = []
  const hits = scriptHits(sample)
  for (const [name, spans] of Object.entries(hits)) {
    if (spans.length) reasons.push(`Unrequested ${name} script in Spanish lyrics.`)
  }
  if (englishLineContamination(sample)) reasons.push('A sung line looks like English rather than Spanish.')
  const words = latinWords(sample).map(word => word.toLocaleLowerCase())
  if (words.length >= 8) {
    const english = words.filter(word => ENGLISH_MARKERS.has(word)).length
    const spanish = words.filter(word => SPANISH_MARKERS.has(word)).length
    if (spanish === 0 && english >= 3) reasons.push('The lyric does not show evidence of Spanish.')
    else if (english >= spanish + 4 && english >= 5) reasons.push('English function words dominate a Spanish lyric.')
  }
  return { mismatch: reasons.length > 0, reasons }
}

export function validateLyricsLanguage(
  lyrics: string,
  lyricsLanguage: string,
  options: { protectedSegments?: readonly ProtectedLyricSegment[]; instrumental?: boolean } = {},
): LyricsLanguageReport {
  const text = lyrics || ''
  if (options.instrumental) {
    const ok = !text.trim() || /^\[?instrumental\]?$/i.test(text.trim())
    return {
      ok, lyrics: ok ? text : '', repaired: false,
      reasons: ok ? [] : ['An instrumental song must not contain vocal lyrics.'],
      languageMismatch: false, strippedSpans: [],
    }
  }
  const protectedList = protectedTexts(options.protectedSegments)
  const masked = maskProtected(text, protectedList)
  const sample = restoreProtected(
    stripTags(masked).replace(/\{\{PROTECTED_\d+\}\}/g, ' '),
    [],
  )
  const code = canonicalLyricsLanguage(lyricsLanguage)
  let reasons: string[] = []
  let mismatch = false
  if (code === 'es') {
    const result = spanishMismatch(sample)
    reasons = result.reasons
    mismatch = result.mismatch
  } else if (code === 'en') {
    for (const [name, spans] of Object.entries(scriptHits(sample))) {
      if (spans.length) {
        mismatch = true
        reasons.push(`Unrequested ${name} script in English lyrics.`)
      }
    }
  }
  return { ok: reasons.length === 0, lyrics: text, repaired: false, reasons, languageMismatch: mismatch, strippedSpans: [] }
}

export function repairLyricsLanguage(
  lyrics: string,
  lyricsLanguage: string,
  options: { protectedSegments?: readonly ProtectedLyricSegment[]; instrumental?: boolean } = {},
): LyricsLanguageReport {
  const first = validateLyricsLanguage(lyrics, lyricsLanguage, options)
  if (first.ok || options.instrumental) return first
  const protectedList = protectedTexts(options.protectedSegments)
  let masked = maskProtected(lyrics || '', protectedList)
  const strippedSpans: { script: string; text: string }[] = []
  for (const [name, pattern] of Object.entries(SCRIPT_RUNS)) {
    masked = masked.replace(new RegExp(pattern.source, 'g'), match => {
      strippedSpans.push({ script: name, text: match })
      return ' '
    })
  }
  const restored = restoreProtected(masked, protectedList)
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .split('\n').map(line => line.trimEnd()).join('\n').trim()
  const second = validateLyricsLanguage(restored, lyricsLanguage, options)
  second.repaired = restored !== (lyrics || '').trim()
  second.strippedSpans = strippedSpans
  if (second.repaired && !second.ok) {
    second.reasons = [...second.reasons, 'Bounded repair stripped foreign scripts but did not invent a translation.']
  }
  return second
}
