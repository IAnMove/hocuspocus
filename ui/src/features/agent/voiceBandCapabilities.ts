import type { defineCapability } from './capabilityRegistry'
import { fetchCharacterKitLibrary, setCharacterVoiceBand } from '../../api/characters'
import { findAnimationKit } from './characterAnimationCapabilities'

/**
 * "Este personaje es un hombre": store the pitch band the server render uses when it records his lines.
 * One operation behind the Wizard, MCP `characters.voice.band` and POST .../voice-band.
 */
export interface AgentSetVoiceBandAction {
  type: 'set_voice_band'
  kitName: string
  voiceType?: 'man' | 'woman' | 'child' | 'robot'
  pitchBandHz?: [number, number]
  maxBrightness?: number
  maxCentroidHz?: number
  language?: string
}

const TYPES = ['man', 'woman', 'child', 'robot'] as const
const text = (value: unknown, limit: number): string => typeof value === 'string' ? value.trim().slice(0, limit) : ''

function bandOf(raw: Record<string, unknown>): Pick<AgentSetVoiceBandAction, 'voiceType' | 'pitchBandHz' | 'maxBrightness' | 'maxCentroidHz'> | null {
  const voiceType = text(raw.voice_type, 20)
  const named = voiceType ? TYPES.includes(voiceType as typeof TYPES[number]) ? voiceType as AgentSetVoiceBandAction['voiceType'] : null : undefined
  if (voiceType && !named) return null
  const pair = raw.pitch_band_hz
  const pitchBandHz = Array.isArray(pair) && pair.length === 2 && pair.every(item => typeof item === 'number') ? [pair[0], pair[1]] as [number, number] : undefined
  if (pair !== undefined && !pitchBandHz) return null
  const maxBrightness = typeof raw.max_brightness === 'number' ? raw.max_brightness : undefined
  const maxCentroidHz = typeof raw.max_centroid_hz === 'number' ? raw.max_centroid_hz : undefined
  if (!named && !pitchBandHz && maxBrightness === undefined && maxCentroidHz === undefined) return null
  return { ...(named ? { voiceType: named } : {}), ...(pitchBandHz ? { pitchBandHz } : {}),
    ...(maxBrightness !== undefined ? { maxBrightness } : {}), ...(maxCentroidHz !== undefined ? { maxCentroidHz } : {}) }
}

export async function executeSetVoiceBand(action: AgentSetVoiceBandAction, workspace?: string) {
  const space = workspace || 'default'
  const library = await fetchCharacterKitLibrary(space)
  const kit = findAnimationKit(library.kits, library.activeId, action.kitName)
  const saved = await setCharacterVoiceBand(space, kit.id, {
    baseRevision: library.revision,
    ...(action.voiceType ? { voiceType: action.voiceType } : {}),
    ...(action.pitchBandHz ? { pitchBandHz: action.pitchBandHz } : {}),
    ...(action.maxBrightness !== undefined ? { maxBrightness: action.maxBrightness } : {}),
    ...(action.maxCentroidHz !== undefined ? { maxCentroidHz: action.maxCentroidHz } : {}),
    ...(action.language ? { language: action.language } : {}),
  })
  return {
    message: `Voice band saved for ${kit.name}.`,
    metadata: saved as unknown as Record<string, unknown>,
    target: { kind: 'character_kit' as const, id: kit.id, title: kit.name },
  }
}

export function registerVoiceBandCapabilities(register: typeof defineCapability) {
  register<AgentSetVoiceBandAction>({
    name: 'set_voice_band',
    title: 'Set a character voice band',
    description: 'Store the pitch and brightness band of one saved character (man, woman, child or robot, or an explicit pitch_band_hz). The server render retries a spoken line outside that band and warns voice_out_of_band when none of the three seeds lands inside. A voice without a band is recorded as before.',
    useWhen: 'The user says what kind of voice a saved character has ("es un hombre", "voz de niño", "el robot no puede sonar tan agudo") or gives a pitch band.',
    parameters: ['kit_name', 'voice_type', 'pitch_band_hz', 'max_brightness', 'max_centroid_hz', 'language'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'set_voice_band' }, kit_name: { type: 'string', maxLength: 160 },
        voice_type: { enum: [...TYPES] },
        pitch_band_hz: { type: 'array', minItems: 2, maxItems: 2, items: { type: 'number' } },
        max_brightness: { type: 'number', minimum: 0, maximum: 1 },
        max_centroid_hz: { type: 'number' },
        language: { type: 'string', maxLength: 40 },
      },
      required: ['type'],
    },
    risk: 'edit', confirmation: 'none', progress: 'Setting the voice band',
    resolve(raw) {
      const band = bandOf(raw)
      if (!band) return null
      const language = text(raw.language, 40)
      return { type: 'set_voice_band', kitName: text(raw.kit_name, 160), ...band, ...(language ? { language } : {}) }
    },
    validate(action) {
      return action.voiceType || action.pitchBandHz || action.maxBrightness !== undefined || action.maxCentroidHz !== undefined ? [] : ['a voice type or a band is required']
    },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.characterKit.setVoiceBand(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'character_kit', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'character_kit', anchors: ['voice'], replay: 'atomic' },
  })
}
