import type { CharacterKit, CharacterKitAsset, CharacterMouthState } from '../../lib/characterKit'
import type { ParseKeys } from 'i18next'
import i18n from '../../i18n'

export type CharacterKitEditorTab = 'kit' | 'face-rig'

export type CharacterKitPoseOption = {
  id: string
  label: string
  source?: string
  approved: boolean
}

export type CharacterKitNextStep = {
  id: 'pick-character' | 'add-body' | 'wipe-mouth' | 'make-mouths' | 'put-on-scene'
  title: string
  detail: string
  tab: CharacterKitEditorTab
}

const KNOWN_POSES = ['base', 'pointing', 'reaction'] as const

const MOUTH_STATES: CharacterMouthState[] = ['closed', 'small', 'wide', 'round']

function tCharacters(key: ParseKeys<'characters'>, options?: Record<string, unknown>): string {
  return i18n.t(key, { ns: 'characters', ...options })
}

export function characterKitPoseLabel(poseId: string): string {
  const id = poseId.trim() || 'base'
  if ((KNOWN_POSES as readonly string[]).includes(id)) return tCharacters(`poses.${id}` as ParseKeys<'characters'>)
  return id.replace(/[-_]+/g, ' ')
}

export function characterKitPoseAsset(kit: CharacterKit, poseId: string): CharacterKitAsset | undefined {
  const id = poseId.trim() || 'base'
  return id === 'base' ? kit.base : kit.poses[id]
}

export function characterKitPoseOptions(kit: CharacterKit): CharacterKitPoseOption[] {
  const options: CharacterKitPoseOption[] = []
  if (kit.base) {
    options.push({
      id: 'base',
      label: characterKitPoseLabel('base'),
      source: kit.base.source,
      approved: kit.base.reviewState === 'approved',
    })
  }
  for (const [id, asset] of Object.entries(kit.poses)) {
    options.push({
      id,
      label: characterKitPoseLabel(id),
      source: asset.source,
      approved: asset.reviewState === 'approved',
    })
  }
  return options
}

export function characterKitApprovedMouths(kit: CharacterKit): CharacterMouthState[] {
  return MOUTH_STATES.filter(state => kit.mouth[state]?.reviewState === 'approved')
}

export function poseMouthWasWiped(kit: CharacterKit, poseId: string): boolean {
  const id = poseId.trim() || 'base'
  return kit.provenance.some(entry => entry.method === 'character-kit-mouth-wipe' && entry.poseId === id)
}

export function poseMouthsAreLocked(kit: CharacterKit, poseId: string): boolean {
  const id = poseId.trim() || 'base'
  if (kit.provenance.some(entry => entry.method === 'character-kit-face-rig-lock-mouths' && entry.poseId === id)) return true
  const states = kit.anchors[id]?.mouthStates
  if (!states) return false
  const first = states.closed ?? states.small ?? states.wide ?? states.round
  if (!first) return false
  return MOUTH_STATES.every(state => {
    const current = states[state]
    return current
      && current.offsetX === first.offsetX
      && current.offsetY === first.offsetY
      && current.scale === first.scale
  })
}

export function characterKitOpeningTab(kit: CharacterKit): CharacterKitEditorTab {
  return characterKitPoseOptions(kit).some(pose => pose.approved) ? 'face-rig' : 'kit'
}

export function characterKitNextStep(kit: CharacterKit | null, poseId = 'base'): CharacterKitNextStep {
  if (!kit) {
    return {
      id: 'pick-character',
      title: tCharacters('guide.pickCharacter.title'),
      detail: tCharacters('guide.pickCharacter.detail'),
      tab: 'kit',
    }
  }
  const pose = characterKitPoseAsset(kit, poseId)
  const poseName = characterKitPoseLabel(poseId)
  if (!pose) {
    return {
      id: 'add-body',
      title: tCharacters('guide.missingBody.title'),
      detail: tCharacters('guide.missingBody.detail', { pose: poseName }),
      tab: 'kit',
    }
  }
  if (pose.reviewState !== 'approved') {
    return {
      id: 'add-body',
      title: tCharacters('guide.approveBody.title', { pose: poseName }),
      detail: tCharacters('guide.approveBody.detail'),
      tab: 'kit',
    }
  }
  if (!poseMouthWasWiped(kit, poseId) || !poseMouthsAreLocked(kit, poseId)) {
    return {
      id: 'wipe-mouth',
      title: tCharacters('guide.wipeMouth.title'),
      detail: tCharacters('guide.wipeMouth.detail', { pose: poseName }),
      tab: 'face-rig',
    }
  }
  if (characterKitApprovedMouths(kit).length < 2) {
    return {
      id: 'make-mouths',
      title: tCharacters('guide.makeMouths.title'),
      detail: tCharacters('guide.makeMouths.detail'),
      tab: 'face-rig',
    }
  }
  return {
    id: 'put-on-scene',
    title: tCharacters('guide.putOnScene.title'),
    detail: tCharacters('guide.putOnScene.detail', { name: kit.name, pose: poseName }),
    tab: 'face-rig',
  }
}
