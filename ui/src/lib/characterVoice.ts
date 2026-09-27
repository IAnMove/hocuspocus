/** Public preferences only. Credentials always stay in the server configuration. */
export type PresetCharacterVoice = {
  provider: 'local'
  model: 'qwen3_tts_customvoice'
  voiceId: string
  instructions?: string
}
export const CHARACTER_VOICE_LANGUAGES = ['auto', 'chinese', 'english', 'japanese', 'korean', 'german', 'french', 'russian', 'portuguese', 'spanish', 'italian'] as const
export type CustomCharacterVoice = {
  provider: 'local'
  model: 'qwen3_tts_base'
  voiceId: 'reference'
  name: string
  referenceAudio: string
  transcript: string
  language: typeof CHARACTER_VOICE_LANGUAGES[number]
}
export type CharacterVoice = PresetCharacterVoice | CustomCharacterVoice
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
function parseCustomCharacterVoice(data: Record<string, unknown>): CustomCharacterVoice {
  if (Object.keys(data).some(key => !['provider', 'model', 'voiceId', 'name', 'referenceAudio', 'transcript', 'language'].includes(key))
    || data.provider !== 'local' || data.voiceId !== 'reference' || !boundedText(data.name, 120) || !boundedText(data.transcript, 4000)
    || !CHARACTER_VOICE_LANGUAGES.includes(data.language as typeof CHARACTER_VOICE_LANGUAGES[number])) {
    throw new Error('Add a named local reference recording, its transcript and a supported language.')
  }
  return { provider: 'local', model: 'qwen3_tts_base', voiceId: 'reference', name: data.name.trim(),
    referenceAudio: parseCharacterVoiceReference(data.referenceAudio), transcript: data.transcript.trim(),
    language: data.language as CustomCharacterVoice['language'] }
}

export function parseCharacterVoice(raw: unknown): CharacterVoice | undefined {
  if (raw === undefined) return undefined
  if (!raw || typeof raw !== 'object') throw new Error('Invalid character voice.')
  const data = raw as Record<string, unknown>
  if (data.model === 'qwen3_tts_base') return parseCustomCharacterVoice(data)
  if (Object.keys(data).some(key => !['provider', 'model', 'voiceId', 'instructions'].includes(key))
    || data.provider !== 'local' || data.model !== 'qwen3_tts_customvoice'
    || !CHARACTER_VOICES.includes(data.voiceId as typeof CHARACTER_VOICES[number])
    || (data.instructions !== undefined && (typeof data.instructions !== 'string' || data.instructions.length > 1000))) {
    throw new Error('Choose a local Qwen3 CustomVoice preset. Do not store credentials in a character.')
  }
  return { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: data.voiceId as string,
    ...(data.instructions ? { instructions: data.instructions as string } : {}) }
}
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
