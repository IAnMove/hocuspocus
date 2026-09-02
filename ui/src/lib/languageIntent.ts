export const VERBATIM_CONTENT_KINDS = [
  'dialogue', 'lyrics', 'visible_text', 'subtitle', 'name',
] as const

export type VerbatimContentKind = typeof VERBATIM_CONTENT_KINDS[number]
export type TechnicalPromptLanguage = 'auto' | 'en'

export interface VerbatimContentSegment {
  kind: VerbatimContentKind
  text: string
  language: string
  speaker?: string
}

/**
 * Language is not one setting. This contract deliberately keeps the user's
 * conversation, the authored work and the provider-facing prompt separate.
 * Exact text is stored as data so prompt compilation can never translate it
 * accidentally.
 */
export interface LanguageIntent {
  conversationLanguage: string
  contentLanguage: string
  spokenLanguage: string
  technicalPromptLanguage: TechnicalPromptLanguage
  verbatimSegments: VerbatimContentSegment[]
}

export const LANGUAGE_INTENT_SCHEMA: Record<string, unknown> = {
  type: 'object',
  additionalProperties: false,
  properties: {
    conversation_language: { type: 'string', maxLength: 120 },
    content_language: { type: 'string', maxLength: 120 },
    spoken_language: { type: 'string', maxLength: 120 },
    technical_prompt_language: { type: 'string', enum: ['auto', 'en'] },
    verbatim_segments: {
      type: 'array',
      maxItems: 40,
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          kind: { type: 'string', enum: [...VERBATIM_CONTENT_KINDS] },
          text: { type: 'string', minLength: 1, maxLength: 12_000 },
          language: { type: 'string', maxLength: 120 },
          speaker: { type: 'string', maxLength: 300 },
        },
        required: ['kind', 'text'],
      },
    },
  },
}

const kinds = new Set<string>(VERBATIM_CONTENT_KINDS)

function text(value: unknown, maximum: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maximum) : ''
}

function segments(value: unknown): VerbatimContentSegment[] {
  if (!Array.isArray(value)) return []
  return value.slice(0, 40).flatMap(candidate => {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return []
    const raw = candidate as Record<string, unknown>
    const kind = text(raw.kind, 40)
    const literal = typeof raw.text === 'string' ? raw.text.slice(0, 12_000) : ''
    if (!kinds.has(kind) || !literal.trim()) return []
    const speaker = text(raw.speaker, 300)
    return [{
      kind: kind as VerbatimContentKind,
      text: literal,
      language: text(raw.language, 120),
      ...(speaker ? { speaker } : {}),
    }]
  })
}

export function normalizeLanguageIntent(
  value: unknown,
  fallback: Partial<LanguageIntent> = {},
): LanguageIntent {
  const raw = value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
  const technical = text(
    raw.technical_prompt_language ?? raw.technicalPromptLanguage ?? fallback.technicalPromptLanguage,
    20,
  )
  return {
    conversationLanguage: text(
      raw.conversation_language ?? raw.conversationLanguage ?? fallback.conversationLanguage,
      120,
    ),
    contentLanguage: text(raw.content_language ?? raw.contentLanguage ?? fallback.contentLanguage, 120),
    spokenLanguage: text(raw.spoken_language ?? raw.spokenLanguage ?? fallback.spokenLanguage, 120),
    technicalPromptLanguage: technical === 'auto' ? 'auto' : 'en',
    verbatimSegments: segments(raw.verbatim_segments ?? raw.verbatimSegments ?? fallback.verbatimSegments),
  }
}

const COMMON_LANGUAGE_TAGS: Record<string, string> = {
  arabic: 'ar', arabe: 'ar',
  chinese: 'zh', chino: 'zh', 中文: 'zh',
  dutch: 'nl', neerlandes: 'nl', neerlandés: 'nl',
  english: 'en', ingles: 'en', inglés: 'en',
  french: 'fr', frances: 'fr', francés: 'fr',
  german: 'de', aleman: 'de', alemán: 'de',
  italian: 'it', italiano: 'it',
  japanese: 'ja', japones: 'ja', japonés: 'ja', 日本語: 'ja',
  korean: 'ko', coreano: 'ko', 한국어: 'ko',
  portuguese: 'pt', portugues: 'pt', portugués: 'pt',
  russian: 'ru', ruso: 'ru',
  spanish: 'es', espanol: 'es', español: 'es',
}

export function normalizeConversationLanguageTag(value: unknown): string {
  const candidate = text(value, 120)
  if (!candidate) return ''
  const lowered = candidate.toLocaleLowerCase().normalize('NFKC')
  if (COMMON_LANGUAGE_TAGS[lowered]) return COMMON_LANGUAGE_TAGS[lowered]
  return /^[a-z]{2,3}(?:-[a-z0-9]{2,8})*$/i.test(candidate) ? candidate : ''
}

export function mergeLanguageIntent(
  current: LanguageIntent | undefined,
  update: LanguageIntent | undefined,
  fallback: Partial<LanguageIntent> = {},
): LanguageIntent {
  const base = normalizeLanguageIntent(current, fallback)
  if (!update) return base
  const exactSegments = new Map(base.verbatimSegments.map(segment => [
    [segment.kind, segment.language, segment.speaker || '', segment.text].join('\u0000'),
    segment,
  ]))
  for (const segment of update.verbatimSegments) {
    exactSegments.set(
      [segment.kind, segment.language, segment.speaker || '', segment.text].join('\u0000'),
      segment,
    )
  }
  return {
    conversationLanguage: update.conversationLanguage || base.conversationLanguage,
    contentLanguage: update.contentLanguage || base.contentLanguage,
    spokenLanguage: update.spokenLanguage || base.spokenLanguage,
    technicalPromptLanguage: update.technicalPromptLanguage || base.technicalPromptLanguage,
    verbatimSegments: [...exactSegments.values()].slice(-40),
  }
}

export function hasLanguageIntent(value: unknown): boolean {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const raw = value as Record<string, unknown>
  const intent = normalizeLanguageIntent(value)
  const explicitTechnicalLanguage = raw.technical_prompt_language ?? raw.technicalPromptLanguage
  return Boolean(
    intent.conversationLanguage
    || intent.contentLanguage
    || intent.spokenLanguage
    || intent.verbatimSegments.length
    || explicitTechnicalLanguage === 'auto'
    || explicitTechnicalLanguage === 'en'
  )
}

export interface ProviderPromptOptions {
  medium: 'video' | 'image' | 'speech' | 'music' | 'sfx' | '3d' | 'story' | 'series' | 'comic'
}

const QUOTED_LITERAL = /["“«]([^"”»\n]{1,12000})["”»]/gu
const TECHNICAL_QUOTE_PREFIX = /(?:style|estilo|prompt|look|aspecto|esthétique|stil|stile)\s*(?::|=|es|is)?\s*$/iu
const LITERAL_CUES: Array<[VerbatimContentKind, RegExp]> = [
  ['lyrics', /\b(?:lyrics?|letra|canci[oó]n|estribillo|coro|verso|chorus|verse|refrain|paroles|liedtext|testo)\b/iu],
  ['subtitle', /\b(?:subt[ií]tulo|subtitle|sous-titre|untertitel|sottotitolo)\b/iu],
  ['visible_text', /\b(?:cartel|r[oó]tulo|texto visible|sign|visible text|panneau|texte visible|schild|sichtbarer text|cartello|testo visibile)\b/iu],
  ['name', /\b(?:titulado|llamad[oa]|named|titled|nomm[eé]|intitul[eé]|genannt|namens|intitolat[oa])\b/iu],
  ['dialogue', /\b(?:diga|digan|dice|decir|hable|habla|di[aá]logo|say|says|speak|dialogue|dialog|dit|dire|parle|sagt|sprechen|dialog|dice|parla|dialogo)\b/iu],
]
const EXPLICIT_LANGUAGE = /\b(?:en|in|idioma|language|langue|sprache|lingua)\s+(espa[nñ]ol|castellano|spanish|english|ingl[eé]s|fran[cç]ais|franc[eé]s|french|deutsch|alem[aá]n|german|italiano|italian|portugu[eê]s|portuguese|japanese|japon[eé]s|korean|coreano|chinese|chino|arabic|[a-z]{2,3}(?:-[a-z0-9]{2,8})*)\b/iu

/**
 * Deterministic safety net for exact user-authored text. The LLM should emit
 * these segments itself, but quoted dialogue/lyrics must not depend on model
 * compliance. Technical style/prompt quotations are deliberately excluded.
 */
export function extractVerbatimSegments(request: string): VerbatimContentSegment[] {
  const result: VerbatimContentSegment[] = []
  for (const match of request.matchAll(QUOTED_LITERAL)) {
    const literal = match[1]
    const start = match.index || 0
    const prefix = request.slice(Math.max(0, start - 120), start)
    const context = `${prefix} ${request.slice(start + match[0].length, start + match[0].length + 80)}`
    if (TECHNICAL_QUOTE_PREFIX.test(prefix)) continue
    const kind = LITERAL_CUES.find(([, cue]) => cue.test(context))?.[0]
    if (!kind) continue
    const explicitLanguage = context.match(EXPLICIT_LANGUAGE)?.[1] || ''
    result.push({
      kind,
      text: literal,
      language: normalizeConversationLanguageTag(explicitLanguage),
    })
  }
  return result
}

const LANGUAGE_CONTRACT_MARKER = 'HOCUSPOCUS LANGUAGE CONTRACT'
const VERBATIM_KINDS_BY_MEDIUM: Record<ProviderPromptOptions['medium'], ReadonlySet<VerbatimContentKind>> = {
  video: new Set(['dialogue', 'visible_text', 'subtitle', 'name']),
  image: new Set(['visible_text', 'name']),
  speech: new Set(['dialogue', 'subtitle', 'name']),
  music: new Set(['lyrics', 'name']),
  sfx: new Set(['name']),
  '3d': new Set(['visible_text', 'name']),
  story: new Set(VERBATIM_CONTENT_KINDS),
  series: new Set(VERBATIM_CONTENT_KINDS),
  comic: new Set(VERBATIM_CONTENT_KINDS),
}

/**
 * Adds an English provider contract around an already authored technical
 * prompt. It never translates or rewrites user-authored literals. The Wizard
 * is responsible for writing the non-literal `prompt` field in English; this
 * compiler makes the boundary explicit and auditable at the visible form.
 */
export function compileProviderPrompt(
  prompt: string,
  intent: LanguageIntent | undefined,
  options: ProviderPromptOptions,
): string {
  const source = prompt.trim()
  if (!intent || source.includes(LANGUAGE_CONTRACT_MARKER)) return source
  const normalized = normalizeLanguageIntent(intent)
  const applicableKinds = VERBATIM_KINDS_BY_MEDIUM[options.medium]
  const applicableSegments = normalized.verbatimSegments.filter(segment => applicableKinds.has(segment.kind))
  const omittedSegments = normalized.verbatimSegments.length - applicableSegments.length
  const lines = [
    `--- ${LANGUAGE_CONTRACT_MARKER} ---`,
    normalized.technicalPromptLanguage === 'auto'
      ? 'Technical direction language: use the language best supported by the selected provider.'
      : 'Technical direction language: English. All non-verbatim visual, camera, performance and production instructions must be interpreted in English.',
    normalized.contentLanguage ? `Authored content language: ${normalized.contentLanguage}.` : '',
    normalized.spokenLanguage && ['video', 'speech', 'music', 'story', 'series', 'comic'].includes(options.medium)
      ? `Spoken or sung language: ${normalized.spokenLanguage}. Use native pronunciation and do not switch languages unless an exact segment says so.`
      : '',
    ...applicableSegments.map((segment, index) => {
      const speaker = segment.speaker ? `; speaker: ${segment.speaker}` : ''
      const language = segment.language ? `; language: ${segment.language}` : ''
      return [
        `Exact ${segment.kind} ${index + 1}${language}${speaker}: ${JSON.stringify(segment.text)}`,
        'Preserve that exact text character-for-character. Do not translate, paraphrase, normalize spelling or merge it with technical instructions.',
      ].join('\n')
    }),
    omittedSegments
      ? `${omittedSegments} protected segment(s) apply to another medium and remain metadata only; do not render or synthesize them here.`
      : '',
    `--- END ${LANGUAGE_CONTRACT_MARKER} ---`,
  ].filter(Boolean)
  return [source, lines.join('\n')].filter(Boolean).join('\n\n')
}

export function languageContractSummary(intent: LanguageIntent | undefined): string {
  if (!intent) return ''
  const normalized = normalizeLanguageIntent(intent)
  return [
    normalized.contentLanguage ? `Content language: ${normalized.contentLanguage}.` : '',
    normalized.spokenLanguage ? `Spoken language: ${normalized.spokenLanguage}.` : '',
    `Provider-facing technical prompts: ${normalized.technicalPromptLanguage === 'auto' ? 'provider-preferred language' : 'English'}.`,
    normalized.verbatimSegments.length
      ? `${normalized.verbatimSegments.length} exact text segment(s) are protected from translation.`
      : '',
  ].filter(Boolean).join(' ')
}
