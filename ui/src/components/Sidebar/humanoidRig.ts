import type { RigAnimation, RigCapabilities, RigProfile, RigProfileId } from '../../api/model3d'

const HUMANOID_RECOMMENDED = ['walk', 'wave', 'dance_side']

export function clipsForEngine(engineId: string, capabilities: RigCapabilities | null, profile: RigProfile | undefined): RigAnimation[] {
  if (engineId === 'humanoid') return capabilities?.humanoid_animations ?? []
  const animations = capabilities?.animations ?? []
  if (!profile) return animations
  return animations.filter(animation => profile.allowed_animations.includes(animation.id))
}

export function recommendedClipIds(engineId: string, capabilities: RigCapabilities | null, profile: RigProfile | undefined, visible: RigAnimation[]): string[] {
  if (engineId === 'humanoid') {
    const ids = new Set((capabilities?.humanoid_animations ?? []).map(item => item.id))
    return HUMANOID_RECOMMENDED.filter(id => ids.has(id))
  }
  return profile?.recommended_animations ?? visible.map(animation => animation.id)
}

export function clipIsRecommended(engineId: string, animationId: string, profile: RigProfile | undefined, recommended: string[]): boolean {
  if (engineId === 'humanoid') return recommended.includes(animationId)
  return Boolean(profile?.recommended_animations.includes(animationId))
}

export function humanoidClipSelection(ids: string[]): string[] {
  const preferred = HUMANOID_RECOMMENDED.filter(id => ids.includes(id))
  if (preferred.length) return preferred
  return ids.slice(0, 1)
}

export function rigHelpKey(engineId: string): 'rig.proceduralHelp' | 'rig.humanoidHelp' | 'rig.unirigHelp' {
  if (engineId === 'procedural') return 'rig.proceduralHelp'
  if (engineId === 'humanoid') return 'rig.humanoidHelp'
  return 'rig.unirigHelp'
}

export function rigFooterKey(engineId: string): 'rig.unirigFooter' | 'rig.humanoidFooter' | 'rig.proceduralFooter' {
  if (engineId === 'unirig') return 'rig.unirigFooter'
  if (engineId === 'humanoid') return 'rig.humanoidFooter'
  return 'rig.proceduralFooter'
}

export function rigJobBody(input: {
  source: string
  engineId: string
  rigProfileId: RigProfileId
  clips: string[]
  pose: 't' | 'a'
  spineJoints: number
  axisMode: 'auto' | 'x' | 'y' | 'z'
  weightFalloff: number
}): {
  source: string
  engine: string
  rig_profile: RigProfileId
  animations: string[]
  pose?: 't' | 'a'
  spine_joints?: number
  axis_mode?: 'auto' | 'x' | 'y' | 'z'
  weight_falloff?: number
} {
  const body = {
    source: input.source,
    engine: input.engineId,
    rig_profile: input.rigProfileId,
    animations: input.clips,
  }
  if (input.engineId === 'humanoid') return { ...body, pose: input.pose }
  return {
    ...body,
    spine_joints: input.spineJoints,
    axis_mode: input.axisMode,
    weight_falloff: input.weightFalloff,
  }
}
