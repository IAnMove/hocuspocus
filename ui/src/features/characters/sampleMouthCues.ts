import type { CharacterKit, CharacterMouthState } from '../../lib/characterKit'
import type { FaceRigDialogueViseme } from '../../lib/characterKitFaceRig'
import { parseMouthCues } from '../scene3d/speech/track'
import { PHONETIC_MOUTH_STATE, MOUTH_STATE_FALLBACK } from '../../lib/characterMouthStates'

export function sampleMouthCues(data: unknown, kit: CharacterKit): FaceRigDialogueViseme[] {
  const fallback = (['wide', 'small', 'round', 'closed'] as const).find(state => kit.mouth[state]?.source)
  return parseMouthCues(data).map(cue => {
    const requested = PHONETIC_MOUTH_STATE[cue.viseme]
    const state: CharacterMouthState = kit.mouth[requested]?.source ? requested : MOUTH_STATE_FALLBACK[requested]
    const sourceState = kit.mouth[state]?.source ? state : fallback ?? state
    return { start: cue.start, end: cue.end, state, sourceState, fallback: state !== sourceState }
  })
}
