import type { CharacterKit, CharacterMouthState } from '../../lib/characterKit'
import type { FaceRigDialogueViseme } from '../../lib/characterKitFaceRig'
import { parseMouthCues } from '../scene3d/speech/track'

const STATES: Record<string, CharacterMouthState> = { rest: 'closed', M: 'closed', I: 'small', E: 'wide', A: 'wide', O: 'round', U: 'round', F: 'small', L: 'small' }
export function sampleMouthCues(data: unknown, kit: CharacterKit): FaceRigDialogueViseme[] {
  const fallback = (['wide', 'small', 'round', 'closed'] as const).find(state => kit.mouth[state]?.source)
  return parseMouthCues(data).map(cue => {
    const state = STATES[cue.viseme], sourceState = kit.mouth[state]?.source ? state : fallback ?? state
    return { start: cue.start, end: cue.end, state, sourceState, fallback: state !== sourceState }
  })
}
