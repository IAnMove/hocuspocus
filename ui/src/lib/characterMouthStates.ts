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
