import { SPOKEN_LANGUAGES, spokenLanguage, type SpokenLanguage } from './speechLanguage'

/** Public preferences only. Credentials always stay in the server configuration. */
export type PresetCharacterVoice = {
  provider: 'local'
  model: 'qwen3_tts_customvoice'
  voiceId: string
  instructions?: string
}
export const CHARACTER_VOICE_LANGUAGES = ['auto', 'chinese', 'english', 'japanese', 'korean', 'german', 'french', 'russian', 'portuguese', 'spanish', 'italian'] as const
/** Speech models that clone a character voice from a reference recording and its transcript. */
export const REFERENCE_VOICE_MODELS = ['voxcpm2_base', 'qwen3_tts_base'] as const
export type ReferenceVoiceModel = typeof REFERENCE_VOICE_MODELS[number]
/** New reference voices start on VoxCPM2. */
export const DEFAULT_REFERENCE_VOICE_MODEL: ReferenceVoiceModel = 'voxcpm2_base'
/** Reference voices that also take a style direction (VoxCPM2 controllable cloning). */
export const STYLED_REFERENCE_VOICE_MODELS: readonly ReferenceVoiceModel[] = ['voxcpm2_base']
export const VOICE_STYLE_MAX_CHARS = 300
export type CustomCharacterVoice = {
  provider: 'local'
  model: ReferenceVoiceModel
  voiceId: 'reference'
  name: string
  referenceAudio: string
  transcript: string
  language: typeof CHARACTER_VOICE_LANGUAGES[number]
  /** VoxCPM2 only: how the cloned voice speaks (whispering, excited…). */
  instructions?: string
}
export type CharacterVoice = PresetCharacterVoice | CustomCharacterVoice
export const isReferenceVoiceModel = (model: unknown): model is ReferenceVoiceModel =>
  REFERENCE_VOICE_MODELS.includes(model as ReferenceVoiceModel)
export const isReferenceVoice = (voice: CharacterVoice | undefined): voice is CustomCharacterVoice =>
  Boolean(voice && isReferenceVoiceModel(voice.model))
/** One dedicated voice per spoken language; the kit's `voice` speaks every other language. */
export type CharacterVoicesByLanguage = Partial<Record<SpokenLanguage, CharacterVoice>>
export type CharacterKitRef = { id: string; workspace: string }
export const CHARACTER_VOICES = ['vivian', 'serena', 'uncle_fu', 'dylan', 'eric', 'ryan', 'aiden', 'ono_anna', 'sohee'] as const

function validateReferenceQuery(kind: string, raw?: string) {
  if (kind === 'uploads') {
    if (raw !== undefined) throw new Error('Upload references cannot contain query parameters.')
    return
  }
  const query = new URLSearchParams(raw), workspace = query.get('workspace')
  if ([...query.keys()].length !== 1 || !workspace || !/^[A-Za-z0-9_. -]{1,120}$/.test(workspace)
    || ['.', '..'].includes(workspace)) throw new Error('The reference recording needs its source workspace.')
}

/** Keep the public asset root and source workspace, never host paths or credentials. */
export function parseCharacterVoiceReference(raw: unknown): string {
  if (typeof raw !== 'string' || !raw || raw.length > 1200 || /[\s\\#]/.test(raw)) throw new Error('Import a local reference recording first.')
  const match = /^\/api\/v1\/(uploads|file)\/([^?]+)(?:\?(.+))?$/.exec(raw)
  if (!match) throw new Error('Use a persistent local reference recording.')
  let path: string
  try { path = decodeURIComponent(match[2]); decodeURIComponent(match[3] ?? '') } catch { throw new Error('Invalid reference recording URL.') }
  if ([...path].some(char => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127) || /[\\%?#]/.test(path)
    || path.split('/').some(part => !part || part.startsWith('.'))
    || !/\.(wav|mp3|m4a|aac|flac|ogg|opus)$/i.test(path)) throw new Error('Choose a local audio recording.')
  validateReferenceQuery(match[1], match[3])
  return raw
}

const boundedText = (raw: unknown, max: number): raw is string => typeof raw === 'string' && Boolean(raw.trim()) && raw.length <= max
function voiceStyle(data: Record<string, unknown>, model: ReferenceVoiceModel): { instructions?: string } {
  if (data.instructions === undefined) return {}
  if (!STYLED_REFERENCE_VOICE_MODELS.includes(model)) throw new Error('This reference voice takes no style direction.')
  if (typeof data.instructions !== 'string' || data.instructions.length > VOICE_STYLE_MAX_CHARS) throw new Error('Voice instructions are too long.')
  return data.instructions.trim() ? { instructions: data.instructions.trim() } : {}
}
function parseCustomCharacterVoice(data: Record<string, unknown>): CustomCharacterVoice {
  const keys = ['provider', 'model', 'voiceId', 'name', 'referenceAudio', 'transcript', 'language', 'instructions']
  if (Object.keys(data).some(key => !keys.includes(key)) || !isReferenceVoiceModel(data.model)
    || data.provider !== 'local' || data.voiceId !== 'reference' || !boundedText(data.name, 120) || !boundedText(data.transcript, 4000)
    || !CHARACTER_VOICE_LANGUAGES.includes(data.language as typeof CHARACTER_VOICE_LANGUAGES[number])) {
    throw new Error('Add a named local reference recording, its transcript and a supported language.')
  }
  return { provider: 'local', model: data.model, voiceId: 'reference', name: data.name.trim(),
    referenceAudio: parseCharacterVoiceReference(data.referenceAudio), transcript: data.transcript.trim(),
    language: data.language as CustomCharacterVoice['language'], ...voiceStyle(data, data.model) }
}

export function parseCharacterVoice(raw: unknown): CharacterVoice | undefined {
  if (raw === undefined) return undefined
  if (!raw || typeof raw !== 'object') throw new Error('Invalid character voice.')
  const data = raw as Record<string, unknown>
  if (isReferenceVoiceModel(data.model)) return parseCustomCharacterVoice(data)
  if (Object.keys(data).some(key => !['provider', 'model', 'voiceId', 'instructions'].includes(key))
    || data.provider !== 'local' || data.model !== 'qwen3_tts_customvoice'
    || !CHARACTER_VOICES.includes(data.voiceId as typeof CHARACTER_VOICES[number])
    || (data.instructions !== undefined && (typeof data.instructions !== 'string' || data.instructions.length > 1000))) {
    throw new Error('Choose a local Qwen3 CustomVoice preset. Do not store credentials in a character.')
  }
  return { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: data.voiceId as string,
    ...(data.instructions ? { instructions: data.instructions as string } : {}) }
}
export function parseCharacterVoicesByLanguage(raw: unknown): CharacterVoicesByLanguage | undefined {
  if (raw === undefined) return undefined
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('Invalid voices by language.')
  const voices: CharacterVoicesByLanguage = {}
  for (const [language, value] of Object.entries(raw)) {
    if (!SPOKEN_LANGUAGES.includes(language as SpokenLanguage)) throw new Error(`Unsupported voice language: ${language}.`)
    const voice = parseCharacterVoice(value)
    if (!voice) continue
    if (isReferenceVoice(voice) && voice.language !== language && voice.language !== 'auto') {
      throw new Error('A reference voice must speak the language it is assigned to.')
    }
    voices[language as SpokenLanguage] = voice
  }
  return Object.keys(voices).length ? voices : undefined
}

/** The voice that speaks `language` ("Español de España", "en", "english"…): its dedicated voice, else the default. */
export function characterVoiceFor(
  kit: { voice?: CharacterVoice; voicesByLanguage?: CharacterVoicesByLanguage } | undefined,
  language?: unknown,
): CharacterVoice | undefined {
  const key = spokenLanguage(language)
  return (key && kit?.voicesByLanguage?.[key]) || kit?.voice
}

export const characterVoiceLabel = (voice: CharacterVoice) => isReferenceVoice(voice) ? voice.name : voice.voiceId
/** Generation params of a cloned voice: its recording and transcript; Qwen3 also takes the
 * language, VoxCPM2 an optional style direction. */
export function referenceVoiceParams(voice: CustomCharacterVoice, referencePath: string | undefined): Record<string, unknown> {
  return {
    audio_prompt_type: 'A', audio_guide: referencePath, alt_prompt: voice.transcript,
    ...(voice.model === 'qwen3_tts_base' ? { model_mode: voice.language } : {}),
    ...(voice.instructions ? { custom_settings: { style: voice.instructions } } : {}),
  }
}
/** The speech engine a voice belongs to, as people know it. */
export const speechEngineName = (model: string) => model.startsWith('voxcpm2') ? 'VoxCPM2' : 'Qwen3'

export function isCharacterVoiceReady(raw: unknown): boolean {
  try { parseCharacterVoice(raw); return true } catch { return false }
}
export function parseCharacterKitRef(raw: unknown): CharacterKitRef | undefined {
  if (raw === undefined) return undefined
  const ref = raw as CharacterKitRef
  if (!ref || typeof ref.id !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(ref.id)
    || typeof ref.workspace !== 'string' || !/^[A-Za-z0-9_. -]{1,120}$/.test(ref.workspace)
    || ['.', '..'].includes(ref.workspace)) throw new Error('Invalid character library reference.')
  return { id: ref.id, workspace: ref.workspace }
}
