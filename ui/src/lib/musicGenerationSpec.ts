import { MINIMAX_MUSIC_COMMUNITY_MODELS } from './minimaxMusicCatalog'

/** Mirrors app/services/music_model_contract.py. Keep limits in both places. */
export const MUSIC_GUIDE_REVISION = 'music-model-contract-v1' as const
export const ACE_DEFAULT_MODEL = 'ace_step_v1_5_xl_sft_lm_4b' as const
export const MUSIC3_LOCAL_MODEL = 'minimax_music3' as const

export const REMOTE_PROMPT_LIMIT = 300
export const REMOTE_LYRICS_LIMIT = 3500
export const LOCAL_PROMPT_LIMIT = 8000
export const LOCAL_LYRICS_LIMIT = 8000
export const DURATION_MIN = 20
export const ACE_DURATION_MAX = 360
export const MUSIC3_DURATION_MAX = 300
export const REMOTE_DURATION_MAX = 240

export type MusicDraftSource = 'story' | 'wizard' | 'ui'
export type MusicRoute = 'local' | 'remote_minimax' | 'unavailable'
export type MusicMode = 'original' | 'instrumental' | 'cover'

export interface MusicGenerationDraft {
  source: MusicDraftSource
  model: string
  caption: string
  lyrics: string
  instrumental?: boolean
  durationSeconds?: number
  lyricsLanguage?: string
  conversationLanguage?: string
  technicalPromptLanguage?: 'auto' | 'en'
  count?: number
}

export interface CompiledMusicRequest {
  backend: 'generateMusic' | 'minimax_api' | null
  model: string
  route: MusicRoute
  prompt: string
  lyrics: string
  instrumental: boolean
  duration_seconds: number
  count: number
  truncated_prompt: boolean
  truncated_lyrics: boolean
}

export interface MusicGenerationSpec {
  schema: 'hocuspocus.music-generation-spec'
  guide_revision: typeof MUSIC_GUIDE_REVISION
  source: MusicDraftSource
  model: string
  route: MusicRoute
  mode: MusicMode
  prompt: string
  lyrics: string
  instrumental: boolean
  count: number
  duration_seconds: number | null
  lyrics_language: string | null
  languages: {
    lyrics: string | null
    conversation: string | null
    technical_prompt: 'auto' | 'en'
  }
  compiled: CompiledMusicRequest
}

export interface MusicModelProfile {
  id: string
  family: string
  route: MusicRoute
  downloadable: boolean
  community: boolean
  promptLimit: number
  lyricsLimit: number
  durationMin: number
  durationMax: number
  countMax: number
  backend: CompiledMusicRequest['backend']
  cover: boolean
}

const COMMUNITY_IDS = new Set(MINIMAX_MUSIC_COMMUNITY_MODELS.map(item => item.id))
const REMOTE_IDS = new Set(['music-3.0', 'music-2.6', 'music-3.0-free', 'music-2.6-free', 'music-cover', 'music-cover-free'])
const COVER_IDS = new Set(['music-cover', 'music-cover-free'])

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : String(value || '').trim()
}

function clamp(value: number, low: number, high: number): number {
  return Math.max(low, Math.min(high, value))
}

function parseCount(raw: unknown, defaultValue: number, max: number): number {
  if (raw === undefined || raw === null || raw === '') return defaultValue
  const numeric = typeof raw === 'number' ? raw : Number(raw)
  if (numeric === 0) return defaultValue
  if (!Number.isInteger(numeric)) {
    throw new Error('Music candidate count must be an integer')
  }
  return clamp(numeric, 1, max)
}

export function catalogEntry(model: string | undefined): MusicModelProfile | null {
  const token = text(model)
  if (!token) return null
  if (token === MUSIC3_LOCAL_MODEL) {
    return {
      id: token, family: 'minimax_music3', route: 'local', downloadable: true, community: false,
      promptLimit: LOCAL_PROMPT_LIMIT, lyricsLimit: LOCAL_LYRICS_LIMIT,
      durationMin: DURATION_MIN, durationMax: MUSIC3_DURATION_MAX, countMax: 1,
      backend: 'generateMusic', cover: false,
    }
  }
  if (COMMUNITY_IDS.has(token)) {
    return {
      id: token, family: 'community', route: 'unavailable', downloadable: false, community: true,
      promptLimit: LOCAL_PROMPT_LIMIT, lyricsLimit: LOCAL_LYRICS_LIMIT,
      durationMin: DURATION_MIN, durationMax: MUSIC3_DURATION_MAX, countMax: 1,
      backend: null, cover: false,
    }
  }
  if (REMOTE_IDS.has(token)) {
    const cover = COVER_IDS.has(token)
    return {
      id: token, family: 'minimax_remote', route: 'remote_minimax', downloadable: false, community: false,
      promptLimit: REMOTE_PROMPT_LIMIT, lyricsLimit: REMOTE_LYRICS_LIMIT,
      durationMin: DURATION_MIN, durationMax: REMOTE_DURATION_MAX, countMax: 3,
      backend: 'minimax_api', cover,
    }
  }
  if (token.startsWith('ace_step') || token === 'ace-step') {
    return {
      id: token === 'ace-step' ? ACE_DEFAULT_MODEL : token,
      family: 'ace_step', route: 'local', downloadable: true, community: false,
      promptLimit: LOCAL_PROMPT_LIMIT, lyricsLimit: LOCAL_LYRICS_LIMIT,
      durationMin: DURATION_MIN, durationMax: ACE_DURATION_MAX, countMax: 1,
      backend: 'generateMusic', cover: false,
    }
  }
  return null
}

export function inspectMusicModel(
  model: string | undefined,
  flags: { installed?: boolean; enabled?: boolean; configured?: boolean; compatible?: boolean } = {},
) {
  const entry = catalogEntry(model)
  const enabled = flags.enabled !== false
  if (!entry) {
    return {
      model: text(model), known: false, downloadable: false, incomplete: false,
      installed: false, compatible: false, configured: false, enabled, available: false,
      route: null as MusicRoute | null, unavailable_reasons: ['Unknown music model.'],
    }
  }
  const compatible = flags.compatible ?? !entry.community
  const local = entry.route === 'local'
  const configured = local ? true : Boolean(flags.configured)
  const installed = local && entry.downloadable ? Boolean(flags.installed) : false
  const reasons: string[] = []
  if (entry.community) reasons.push('Needs a validated adapter; not compatible with the bundled backend.')
  if (!enabled) reasons.push('The model is disabled.')
  if (!compatible) reasons.push('The model is not compatible with this runtime.')
  if (local && entry.downloadable && !installed) reasons.push('Required assets are not installed.')
  if (!local && !configured) reasons.push('The remote provider is not configured.')
  const available = !entry.community && enabled && compatible && configured && (local ? installed : true)
  return {
    model: entry.id,
    known: true,
    downloadable: entry.downloadable,
    incomplete: Boolean(entry.downloadable && local && !installed),
    installed,
    compatible,
    configured,
    enabled,
    available,
    route: entry.route,
    unavailable_reasons: reasons,
  }
}

export function compileMusicRequest(entry: MusicModelProfile, draft: MusicGenerationDraft): CompiledMusicRequest {
  const caption = text(draft.caption)
  const lyrics = draft.instrumental ? '' : text(draft.lyrics)
  const prompt = caption.slice(0, entry.promptLimit)
  const clippedLyrics = lyrics.slice(0, entry.lyricsLimit)
  const duration = clamp(
    Number.isFinite(Number(draft.durationSeconds)) && Number(draft.durationSeconds) > 0
      ? Number(draft.durationSeconds)
      : 90,
    entry.durationMin,
    entry.durationMax,
  )
  const count = parseCount(draft.count, entry.route === 'remote_minimax' ? 2 : 1, entry.countMax)
  return {
    backend: entry.backend,
    model: entry.id,
    route: entry.route,
    prompt,
    lyrics: clippedLyrics,
    instrumental: Boolean(draft.instrumental),
    duration_seconds: duration,
    count,
    truncated_prompt: caption.length > entry.promptLimit,
    truncated_lyrics: lyrics.length > entry.lyricsLimit,
  }
}

export function buildMusicGenerationSpec(draft: MusicGenerationDraft): MusicGenerationSpec {
  const entry = catalogEntry(draft.model)
  if (!entry || entry.community || !entry.backend) {
    throw new Error(`Unknown or unavailable music model: ${draft.model || '(empty)'}`)
  }
  const caption = text(draft.caption)
  const lyrics = draft.instrumental ? '' : text(draft.lyrics)
  const compiled = compileMusicRequest(entry, draft)
  const lyricsLanguage = text(draft.lyricsLanguage) || null
  const requestedDuration = Number.isFinite(Number(draft.durationSeconds)) && Number(draft.durationSeconds) > 0
    ? compiled.duration_seconds
    : null
  return {
    schema: 'hocuspocus.music-generation-spec',
    guide_revision: MUSIC_GUIDE_REVISION,
    source: draft.source,
    model: entry.id,
    route: entry.route,
    mode: entry.cover ? 'cover' : draft.instrumental ? 'instrumental' : 'original',
    prompt: caption,
    lyrics,
    instrumental: Boolean(draft.instrumental),
    count: compiled.count,
    duration_seconds: requestedDuration,
    lyrics_language: lyricsLanguage,
    languages: {
      lyrics: lyricsLanguage,
      conversation: text(draft.conversationLanguage) || null,
      technical_prompt: draft.technicalPromptLanguage === 'auto' ? 'auto' : 'en',
    },
    compiled,
  }
}

export function storyCueToMusicDraft(input: {
  model: string
  style: string
  lyrics: string
  instrumental?: boolean
  durationSeconds?: number
  lyricsLanguage?: string
  conversationLanguage?: string
  technicalPromptLanguage?: 'auto' | 'en'
}): MusicGenerationDraft {
  return {
    source: 'story',
    model: input.model,
    caption: input.style,
    lyrics: input.lyrics,
    instrumental: input.instrumental,
    durationSeconds: input.durationSeconds,
    lyricsLanguage: input.lyricsLanguage,
    conversationLanguage: input.conversationLanguage,
    technicalPromptLanguage: input.technicalPromptLanguage,
    count: 1,
  }
}

export function wizardSongToMusicDraft(input: {
  model: string
  style: string
  lyrics: string
  instrumental?: boolean
  durationSeconds?: number
  lyricsLanguage?: string
  conversationLanguage?: string
}): MusicGenerationDraft {
  return {
    source: 'wizard',
    model: input.model,
    caption: input.style,
    lyrics: input.lyrics,
    instrumental: input.instrumental,
    durationSeconds: input.durationSeconds,
    lyricsLanguage: input.lyricsLanguage,
    conversationLanguage: input.conversationLanguage,
    technicalPromptLanguage: 'en',
    count: 1,
  }
}

export function studioParamsToMusicDraft(input: {
  modelType: string
  altPrompt: string
  prompt: string
  instrumental?: boolean
  durationSeconds?: number
}): MusicGenerationDraft {
  return {
    source: 'ui',
    model: input.modelType,
    caption: input.altPrompt,
    lyrics: input.prompt,
    instrumental: input.instrumental,
    durationSeconds: input.durationSeconds,
    count: 1,
  }
}

export function comparableMusicSpec(spec: MusicGenerationSpec): Omit<MusicGenerationSpec, 'source'> {
  return {
    schema: spec.schema,
    guide_revision: spec.guide_revision,
    model: spec.model,
    route: spec.route,
    mode: spec.mode,
    prompt: spec.prompt,
    lyrics: spec.lyrics,
    instrumental: spec.instrumental,
    count: spec.count,
    duration_seconds: spec.duration_seconds,
    lyrics_language: spec.lyrics_language,
    languages: spec.languages,
    compiled: spec.compiled,
  }
}
