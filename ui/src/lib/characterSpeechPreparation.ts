import { isFacePatchCompatible } from './characterFacePatch'
import type { CharacterKit, CharacterMouthState } from './characterKit'
import { BASIC_MOUTH_STATES, CHARACTER_MOUTH_STATES } from './characterMouthStates'

export type SpeechPreparationStatus = 'missing' | 'pending' | 'rejected' | 'incompatible' | 'approved'

export interface SpeechPreparationReadiness {
  poseApproved: boolean
  rows: Array<{ state: CharacterMouthState, status: SpeechPreparationStatus }>
  previewReady: boolean
  complete: boolean
}

const MOUTH_STATES = CHARACTER_MOUTH_STATES

function poseFor(kit: CharacterKit, poseId: string) {
  return poseId === 'base' ? kit.base : kit.poses[poseId]
}

function hasSource(source: unknown): source is string {
  return typeof source === 'string' && source.trim().length > 0
}

/** Report structural readiness for the fixed 2D speech mouth set. */
export function speechPreparationReadiness(kit: CharacterKit, poseId: string): SpeechPreparationReadiness {
  const normalizedPoseId = poseId.trim() || 'base'
  const pose = poseFor(kit, normalizedPoseId)
  const poseApproved = Boolean(pose && hasSource(pose.source) && pose.reviewState === 'approved')
  const poseSource = hasSource(pose?.source) ? pose.source : ''
  const rows = MOUTH_STATES.map(state => {
    const asset = kit.mouth[state]
    if (!asset || !hasSource(asset.source)) return { state, status: 'missing' as const }
    if (!isFacePatchCompatible(asset, normalizedPoseId, poseSource)) return { state, status: 'incompatible' as const }
    return { state, status: asset.reviewState }
  })
  const approved = new Set(rows.filter(row => row.status === 'approved').map(row => row.state))
  const previewReady = poseApproved && approved.has('closed') && BASIC_MOUTH_STATES.some(state => state !== 'closed' && approved.has(state))
  const complete = poseApproved && MOUTH_STATES.every(state => approved.has(state))
  return { poseApproved, rows, previewReady, complete }
}
