import { explicitMusicLanguage } from '../../lib/labHelpers'
import {
  mergeLanguageIntent,
  normalizeLanguageIntent,
  type LanguageIntent,
  type VerbatimContentSegment,
} from '../../lib/languageIntent'
import type { StoryMusicDraft, StoryProject, StoryWritingProvider } from './types'

/**
 * A song has two different language decisions: the language used to talk to
 * the Wizard and the language in which the lyrics are authored/sung.  Keep
 * the latter resolution in this module so callers do not accidentally fall
 * back to the UI locale or to an unrelated conversation language.
 */
const LANGUAGE_ALIASES: Record<string, string> = {
  ar: 'العربية', arabic: 'العربية', arabe: 'العربية',
  de: 'Deutsch', deutsch: 'Deutsch', german: 'Deutsch', alemán: 'Deutsch', aleman: 'Deutsch',
  en: 'English', english: 'English', inglés: 'English', ingles: 'English',
  es: 'Español', español: 'Español', espanol: 'Español', castellano: 'Español', spanish: 'Español',
  fr: 'Français', français: 'Français', francais: 'Français', french: 'Français', francés: 'Français', frances: 'Français',
  it: 'Italiano', italian: 'Italiano', italiano: 'Italiano',
  ja: '日本語', japanese: '日本語', japonés: '日本語', japones: '日本語',
  ko: '한국어', korean: '한국어', coreano: '한국어',
  nl: 'Nederlands', dutch: 'Nederlands', neerlandés: 'Nederlands', neerlandes: 'Nederlands',
  pt: 'Português', portuguese: 'Português', português: 'Português', portugues: 'Português',
  ru: 'Русский', russian: 'Русский', ruso: 'Русский',
  zh: '中文', chinese: '中文', chino: '中文',
}

const LANGUAGE_NAME_PATTERN = '(?:espa[nñ]ol|castellano|spanish|english|ingl[eé]s|fran[cç]ais|franc[eé]s|french|deutsch|alem[aá]n|german|italiano|italian|portugu[eê]s|portuguese|japanese|japon[eé]s|korean|coreano|chinese|chino|arabic|arabe|russian|ruso|dutch|neerland[eé]s)'
const LANGUAGE_CODE_PATTERN = '(?:es|en|fr|de|it|pt|ja|ko|zh|ar|nl|ru)(?:-[a-z0-9]{2,8})?'

const REQUESTED_LANGUAGE_PATTERNS = [
  new RegExp(`\\b(?:lyrics?|letra(?:s)?|cancion(?:es)?|canci[oó]n(?:es)?|song|vocal|voz)\\b[^.!?\\n]{0,120}?\\b(?:en|in)\\s+(${LANGUAGE_NAME_PATTERN})\\b`, 'iu'),
  new RegExp(`\\b(?:en|in)\\s+(${LANGUAGE_NAME_PATTERN})\\b[^.!?\\n]{0,120}?\\b(?:lyrics?|letra(?:s)?|cancion(?:es)?|canci[oó]n(?:es)?|song|vocal|voz)\\b`, 'iu'),
  new RegExp(`\\b(${LANGUAGE_NAME_PATTERN})\\s+(?:lyrics?|letra(?:s)?|cancion(?:es)?|canci[oó]n(?:es)?|song|vocal)\\b`, 'iu'),
  new RegExp(`\\b(?:idioma|language|langue|sprache|lingua)\\s*(?:de|del|of|en|in|:)?\\s*(${LANGUAGE_NAME_PATTERN}|${LANGUAGE_CODE_PATTERN})\\b`, 'iu'),
] as const

function folded(value: string): string {
  return value
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLocaleLowerCase()
    .trim()
}

function canonicalLanguage(value: string): string {
  const candidate = value.trim()
  if (!candidate) return ''
  const key = folded(candidate)
  return LANGUAGE_ALIASES[key]
    || LANGUAGE_ALIASES[key.split('-')[0]]
    || explicitMusicLanguage(candidate)
}

/** Extract an explicit lyric-language request without looking at UI locale. */
export function extractRequestedSongLanguage(request: string): string {
  const source = request.trim()
  if (!source) return ''
  for (const pattern of REQUESTED_LANGUAGE_PATTERNS) {
    const match = source.match(pattern)
    if (match?.[1]) return canonicalLanguage(match[1])
  }
  return ''
}

export interface SongLanguageResolutionInput {
  request?: string
  requestedLanguage?: string
  languageIntent?: LanguageIntent
  fallback?: string
}

/**
 * Explicit language in the user's request wins over model guesses.  The
 * action field is next, followed by the authored/spoken language contract,
 * and only then the story language/default.  Conversation language is
 * intentionally not consulted here.
 */
export function resolveSongLyricsLanguage({
  request = '',
  requestedLanguage = '',
  languageIntent,
  fallback = 'Español',
}: SongLanguageResolutionInput): string {
  return canonicalLanguage(
    extractRequestedSongLanguage(request)
      || requestedLanguage
      || languageIntent?.spokenLanguage
      || languageIntent?.contentLanguage
      || fallback,
  ) || 'Español'
}

export function resolveStorySongLanguage(
  requestedLanguage: string,
  languageIntent: LanguageIntent | undefined,
  fallback: string,
): string {
  return resolveSongLyricsLanguage({ requestedLanguage, languageIntent, fallback })
}

export function protectedSongLyrics(intent: LanguageIntent): VerbatimContentSegment[] {
  return intent.verbatimSegments.filter(segment => segment.kind === 'lyrics')
}

export function buildSongLyricsDirection(
  lyricsLanguage: string,
  protectedLyrics: readonly VerbatimContentSegment[],
): string {
  return [
    `Write completely original vocal lyrics in ${lyricsLanguage}, with [Verse], [Chorus], [Bridge] and [Outro] sections.`,
    'Do not translate, paraphrase or omit the following protected lyric fragments; include each one character-for-character:',
    ...protectedLyrics.map((segment, index) => `Exact lyric ${index + 1} (${segment.language || lyricsLanguage}): ${JSON.stringify(segment.text)}`),
  ].join('\n')
}

export function storySongSemanticAnchors(input: {
  brief?: string
  premise?: string
  theme?: string
  songStory?: string
}): string[] {
  return extractSongSemanticAnchors([
    input.premise,
    input.theme,
    input.songStory,
    input.brief,
  ].filter(Boolean).join('\n'), 4)
}

export function songProviderLanguageIntent(
  intent: LanguageIntent,
  lyricsLanguage: string,
): LanguageIntent {
  return mergeLanguageIntent(intent, normalizeLanguageIntent({
    spoken_language: lyricsLanguage,
    technical_prompt_language: 'en',
  }))
}

export interface SongLanguageActionOptions {
  current?: LanguageIntent
  conversationLanguage?: string
  contentLanguage?: string
  lyricsLanguage?: string
  verbatimSegments: readonly VerbatimContentSegment[]
  requestedSongLanguage?: string
  request?: string
}

function resolveSongSpokenLanguage(
  actionType: string,
  requestedSongLanguage: string,
  lyricsLanguage: string,
  current: LanguageIntent | undefined,
  explicitSpokenLanguage: string,
  contentLanguage: string,
): string {
  const songLanguage = requestedSongLanguage || lyricsLanguage || current?.spokenLanguage || explicitSpokenLanguage || contentLanguage
  if (actionType === 'configure_story_song') return songLanguage
  return explicitSpokenLanguage || requestedSongLanguage || current?.spokenLanguage || lyricsLanguage || contentLanguage
}

/** Apply the language contract to a parsed Wizard action without coupling the
 * agent parser to Story Lab's song-specific implementation details. */
export function applySongLanguageIntent<T extends {
  type: string
  languageIntent?: LanguageIntent
  language?: string
  lyricsLanguage?: string
}>(action: T, options: SongLanguageActionOptions): T {
  const {
    current,
    conversationLanguage,
    contentLanguage = '',
    lyricsLanguage = '',
    verbatimSegments,
    requestedSongLanguage = '',
    request = '',
  } = options
  const explicitSpokenLanguage = verbatimSegments.find(segment => (
    (segment.kind === 'dialogue' || segment.kind === 'lyrics') && segment.language
  ))?.language || ''
  // A song may intentionally contain a quoted refrain in another language.
  // Its spoken/sung contract is the requested song language; the segment
  // keeps its own language metadata for exact preservation.
  const spokenLanguage = resolveSongSpokenLanguage(
    action.type, requestedSongLanguage, lyricsLanguage, current, explicitSpokenLanguage, contentLanguage,
  )
  const deterministic = normalizeLanguageIntent({
    conversation_language: current?.conversationLanguage || conversationLanguage,
    content_language: current?.contentLanguage || contentLanguage,
    spoken_language: spokenLanguage,
    technical_prompt_language: current?.technicalPromptLanguage || 'en',
    verbatim_segments: verbatimSegments.map(segment => ({
      ...segment,
      language: segment.language || spokenLanguage,
    })),
  })
  const protectedAction = {
    ...action,
    languageIntent: mergeLanguageIntent(current, deterministic),
  } as T
  if (action.type !== 'configure_story_song' || !requestedSongLanguage) return protectedAction
  return {
    ...protectedAction,
    lyricsLanguage: resolveSongLyricsLanguage({
      request,
      requestedLanguage: lyricsLanguage,
      languageIntent: deterministic,
      fallback: contentLanguage,
    }),
  } as T
}

export interface StorySongWritingRequestInput {
  target: Pick<StoryProject, 'title' | 'premise' | 'synopsis' | 'theme' | 'beats'>
  brief: string
  style: string
  lyricsLanguage: string
  protectedLyrics: readonly VerbatimContentSegment[]
  model: StoryMusicDraft['model']
  targetProvider: 'ace-step' | 'minimax'
  durationSeconds: number
  writingProvider: StoryWritingProvider
  writingModel: string
  writingBaseUrl: string
}

export function buildStorySongWritingRequest(input: StorySongWritingRequestInput) {
  const { target, brief, style, lyricsLanguage, protectedLyrics } = input
  const storyContext = [
    `Título: ${target.title}`,
    `Premisa: ${target.premise}`,
    target.synopsis ? `Sinopsis: ${target.synopsis}` : '',
    target.theme ? `Tema: ${target.theme}` : '',
    target.beats.length ? `Progresión: ${target.beats.map(item => item.summary).join(' → ')}` : '',
  ].filter(Boolean).join('\n')
  return {
    description: `${brief}\nWrite the provider-facing music direction in English and the complete lyrics in ${lyricsLanguage}.`,
    instrumental: false as const,
    target: input.targetProvider,
    model: input.model,
    style_direction: `${style}\nReturn the visible provider-facing music direction in English. Do not translate protected literal text.`,
    lyrics_direction: buildSongLyricsDirection(lyricsLanguage, protectedLyrics),
    story_context: storyContext,
    language: lyricsLanguage,
    duration_seconds: input.durationSeconds,
    max_new_tokens: 2200,
    writingProvider: input.writingProvider,
    writingModel: input.writingModel,
    writingBaseUrl: input.writingBaseUrl,
  }
}

export function assertStorySongFidelity(
  lyrics: string,
  lyricsLanguage: string,
  requiredTerms: readonly string[],
  protectedSegments: readonly VerbatimContentSegment[],
): SongSemanticFidelityReport {
  return assertGeneratedSongFidelity({
    lyrics,
    lyricsLanguage,
    instrumental: false,
    requiredTerms,
    protectedSegments,
    requireStructuredLyrics: true,
  })
}

const SEMANTIC_STOP_WORDS = new Set([
  // Spanish, English, French, German, Italian and Portuguese connective and
  // workflow words.  These are not useful evidence that a lyric tells the
  // requested story and must not become mandatory anchors.
  'a', 'al', 'algo', 'cada', 'con', 'como', 'contra', 'cual', 'cuando', 'de', 'del', 'el', 'ella', 'ellas', 'ellos', 'en', 'es', 'esta', 'este', 'esto', 'la', 'las', 'lo', 'los', 'más', 'mi', 'mis', 'no', 'nos', 'para', 'por', 'que', 'se', 'sin', 'su', 'sus', 'un', 'una', 'unos', 'unas', 'y',
  'a', 'about', 'an', 'and', 'are', 'as', 'at', 'be', 'but', 'by', 'for', 'from', 'he', 'her', 'his', 'in', 'is', 'it', 'its', 'of', 'on', 'or', 'our', 'that', 'the', 'their', 'them', 'there', 'this', 'to', 'we', 'with', 'you', 'your',
  'avec', 'dans', 'de', 'des', 'du', 'en', 'et', 'la', 'le', 'les', 'mais', 'par', 'pour', 'que', 'sur', 'un', 'une',
  'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'und', 'ist', 'mit', 'von', 'zu',
  'che', 'con', 'da', 'del', 'della', 'di', 'e', 'gli', 'il', 'in', 'la', 'le', 'per', 'su', 'un', 'una',
  'como', 'da', 'das', 'de', 'do', 'e', 'em', 'para', 'por', 'que', 'um', 'uma',
  'create', 'created', 'creating', 'direction', 'music', 'original', 'song', 'story', 'theme', 'write', 'written', 'lyrics', 'letra', 'cancion', 'canción', 'videoclip', 'video', 'style', 'estilo', 'visual', 'prompt', 'user', 'usuario',
  'heavy', 'metal', 'rock', 'pop', 'anthem', 'himno', 'voice', 'vocal', 'fantasy', 'fantasía', 'fantastica', 'fantástica', 'adult', 'adulta', 'animation', 'animacion', 'animación', 'animated', 'inspired', 'inspirado', 'inspirada', 'inspirados', 'inspiradas', 'classic', 'clásica', 'pelicula', 'película', 'film', 'movie', 'protagonist', 'protagonista', 'character', 'personaje', 'language', 'idioma', 'espanol', 'español', 'english', 'inglés', 'ingles', 'french', 'francés', 'frances', 'german', 'alemán', 'aleman', '1981', '1980s', 'ochentero', 'ochentera',
  'historia', 'premisa', 'sinopsis', 'progresion', 'progresión', 'conflicto', 'central', 'aventura', 'chapter', 'chapters', 'capitulo', 'capítulo', 'etapa', 'etapas', 'momento', 'moments', 'idea', 'general', 'summary', 'resumen',
])

/**
 * Pull a small set of stable, content-bearing anchors from a brief.  This is
 * deliberately conservative: it is an evaluation signal, not an attempt to
 * understand synonyms or replace the model's creative judgment.
 */
export function extractSongSemanticAnchors(source: string, maximum = 6): string[] {
  const seen = new Set<string>()
  const result: string[] = []
  for (const token of source
    .normalize('NFKC')
    .toLocaleLowerCase()
    .match(/[\p{L}\p{N}][\p{L}\p{N}'’-]{2,}/gu) || []) {
    const clean = token.replace(/^[-'’]+|[-'’]+$/g, '')
    const key = folded(clean)
    if (key.length < 4 || SEMANTIC_STOP_WORDS.has(key) || seen.has(key)) continue
    seen.add(key)
    result.push(clean)
    if (result.length >= maximum) break
  }
  return result
}

const LANGUAGE_MARKERS: Record<string, ReadonlySet<string>> = {
  es: new Set(['el', 'la', 'los', 'las', 'que', 'de', 'del', 'en', 'y', 'un', 'una', 'por', 'para', 'con', 'no', 'se', 'es', 'mi', 'tu', 'yo', 'somos', 'noche', 'red', 'canta', 'cantar', 'sangra', 'reinicia']),
  en: new Set(['the', 'and', 'that', 'this', 'with', 'from', 'through', 'night', 'our', 'your', 'you', 'we', 'is', 'are', 'to', 'of', 'in', 'on', 'not', 'fight', 'sing']),
  fr: new Set(['le', 'la', 'les', 'des', 'une', 'un', 'que', 'dans', 'avec', 'pour', 'nous', 'vous', 'est', 'et', 'nuit', 'chante']),
  de: new Set(['der', 'die', 'das', 'den', 'ein', 'eine', 'und', 'mit', 'für', 'wir', 'ist', 'nicht', 'nacht', 'singt']),
  it: new Set(['il', 'lo', 'la', 'gli', 'le', 'un', 'una', 'che', 'con', 'per', 'noi', 'è', 'e', 'notte', 'canta']),
  pt: new Set(['o', 'a', 'os', 'as', 'um', 'uma', 'que', 'de', 'do', 'da', 'em', 'com', 'para', 'por', 'nós', 'é', 'noite', 'canta']),
}

function languageCode(value: string): string {
  const key = folded(value)
  if (key.startsWith('es') || key.includes('spanish') || key.includes('espanol') || key.includes('castellano')) return 'es'
  if (key.startsWith('en') || key.includes('english') || key.includes('ingles')) return 'en'
  if (key.startsWith('fr') || key.includes('french') || key.includes('francais')) return 'fr'
  if (key.startsWith('de') || key.includes('german') || key.includes('deutsch') || key.includes('aleman')) return 'de'
  if (key.startsWith('it') || key.includes('italian') || key.includes('italiano')) return 'it'
  if (key.startsWith('pt') || key.includes('portuguese') || key.includes('portugues')) return 'pt'
  return ''
}

function languageMismatch(
  lyrics: string,
  requestedLanguage: string,
  protectedSegments: readonly VerbatimContentSegment[] = [],
): boolean {
  const code = languageCode(requestedLanguage)
  // A literal refrain may intentionally be in another language. It is
  // checked separately for exact preservation and must not skew the language
  // score for the authored song around it.
  const languageSample = protectedSegments.reduce(
    (source, segment) => source.split(segment.text).join(' '),
    lyrics,
  )
  const words = languageSample.toLocaleLowerCase().match(/[\p{L}]+/gu) || []
  // Very short authored fragments are not reliable language evidence. Exact
  // protected fragments and the requested language metadata still survive.
  if (!code || words.length < 8) return false
  const scores = Object.fromEntries(Object.entries(LANGUAGE_MARKERS).map(([name, markers]) => [
    name,
    words.reduce((score, word) => score + (markers.has(word) ? 1 : 0), 0),
  ]))
  const targetScore = scores[code] || 0
  const strongestOther = Math.max(...Object.entries(scores)
    .filter(([name]) => name !== code)
    .map(([, score]) => score), 0)
  return targetScore === 0 && strongestOther >= 2
    || strongestOther >= targetScore + 3 && strongestOther >= 4
}

export interface SongSemanticFidelityInput {
  lyrics: string
  lyricsLanguage: string
  instrumental?: boolean
  requiredTerms?: readonly string[]
  protectedSegments?: readonly VerbatimContentSegment[]
  requireStructuredLyrics?: boolean
}

export interface SongSemanticFidelityReport {
  ok: boolean
  score: number
  reasons: string[]
  missingTerms: string[]
  missingProtectedSegments: string[]
  languageMismatch: boolean
}

/**
 * Cheap, provider-free guardrail for authored song data. It catches the two
 * regressions that a valid WAV cannot reveal: lyrics in the wrong language
 * and a lyric that no longer contains the requested subject/literal text.
 */
export function evaluateSongSemanticFidelity(input: SongSemanticFidelityInput): SongSemanticFidelityReport {
  const lyrics = input.lyrics.trim()
  const reasons: string[] = []
  const checks: boolean[] = []
  const missingTerms = (input.requiredTerms || []).filter(term => {
    const normalized = folded(term)
    return normalized && !folded(lyrics).includes(normalized)
  })
  const protectedLyrics = (input.protectedSegments || []).filter(segment => segment.kind === 'lyrics')
  const missingProtectedSegments = protectedLyrics
    .filter(segment => !lyrics.includes(segment.text))
    .map(segment => segment.text)

  if (input.instrumental) {
    const valid = !lyrics
    checks.push(valid)
    if (!valid) reasons.push('An instrumental song must not contain vocal lyrics.')
  } else {
    const valid = Boolean(lyrics)
    checks.push(valid)
    if (!valid) reasons.push('A vocal song needs a complete editable lyric.')
    if (input.requireStructuredLyrics) {
      const structured = /\[(?:intro|verse|pre[ -]?chorus|chorus|post[ -]?chorus|interlude|bridge|transition|build[ -]?up|break|hook|inst|solo|outro)\b[^\]]*\]/iu.test(lyrics)
      checks.push(structured)
      if (!structured) reasons.push('The vocal lyric has no recognised sections such as [Verse] or [Chorus].')
    }
  }

  for (const term of input.requiredTerms || []) {
    const present = !missingTerms.includes(term)
    checks.push(present)
  }
  if (missingTerms.length) reasons.push(`Missing requested song subject: ${missingTerms.join(', ')}.`)

  for (const segment of protectedLyrics) {
    const present = !missingProtectedSegments.includes(segment.text)
    checks.push(present)
  }
  if (missingProtectedSegments.length) reasons.push('A protected lyric quotation was changed or translated.')

  const mismatched = !input.instrumental && languageMismatch(lyrics, input.lyricsLanguage, protectedLyrics)
  checks.push(!mismatched)
  if (mismatched) reasons.push(`The lyric does not show evidence of the requested language (${input.lyricsLanguage}).`)

  const score = checks.length
    ? Math.round((checks.filter(Boolean).length / checks.length) * 100)
    : 100
  return {
    ok: reasons.length === 0,
    score,
    reasons,
    missingTerms,
    missingProtectedSegments,
    languageMismatch: mismatched,
  }
}

export function assertGeneratedSongFidelity(
  input: SongSemanticFidelityInput,
): SongSemanticFidelityReport {
  const fidelity = evaluateSongSemanticFidelity(input)
  if (!fidelity.ok) {
    throw new Error(`La letra generada no respeta el idioma o el tema solicitado (${fidelity.score}%): ${fidelity.reasons.join(' ')}`)
  }
  return fidelity
}
