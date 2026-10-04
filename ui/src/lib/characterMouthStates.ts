/** Legacy scenes can use four drawings; newly prepared speech requires all nine slots. */
export const BASIC_MOUTH_STATES = ['closed', 'small', 'wide', 'round'] as const
export const CHARACTER_MOUTH_STATES = [...BASIC_MOUTH_STATES, 'pressed', 'medium', 'pucker', 'bite', 'tongue'] as const
export type CharacterMouthState = typeof CHARACTER_MOUTH_STATES[number]

export const MOUTH_STATE_FALLBACK: Record<CharacterMouthState, typeof BASIC_MOUTH_STATES[number]> = {
  closed: 'closed', small: 'small', wide: 'wide', round: 'round',
  pressed: 'closed', medium: 'wide', pucker: 'round', bite: 'small', tongue: 'small',
}
/** Rhubarb/Scene3D phonetic names → the shared 2D drawing slots. */
export const PHONETIC_MOUTH_STATE: Record<string, CharacterMouthState> = {
  rest: 'closed', M: 'pressed', I: 'small', E: 'medium', A: 'wide',
  O: 'round', U: 'pucker', F: 'bite', L: 'tongue',
}

export const MOUTH_SOUND_GROUPS = ['rest', 'M', 'A', 'E', 'I', 'O', 'U', 'F', 'L'] as const
export type MouthSoundGroup = typeof MOUTH_SOUND_GROUPS[number]
export type CharacterMouthMapping = Partial<Record<MouthSoundGroup, CharacterMouthState>>

/** Older characters inherit the standard assignments. Several sounds can share a drawing. */
export function mouthStateForSound(sound: string, mapping?: CharacterMouthMapping): CharacterMouthState {
  return mapping?.[sound as MouthSoundGroup] ?? PHONETIC_MOUTH_STATE[sound] ?? 'closed'
}

export function normalizeMouthMapping(raw: unknown): CharacterMouthMapping | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const entries = Object.entries(raw)
  if (entries.some(([sound, state]) => !MOUTH_SOUND_GROUPS.includes(sound as MouthSoundGroup)
    || !CHARACTER_MOUTH_STATES.includes(state as CharacterMouthState))) return undefined
  return Object.fromEntries(entries) as CharacterMouthMapping
}

export const MOUTH_MAPPING_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: Object.fromEntries(MOUTH_SOUND_GROUPS.map(sound => [sound, { enum: [...CHARACTER_MOUTH_STATES] }])),
} as const
