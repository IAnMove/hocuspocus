import type { RigAnimation, RigCapabilities, RigJob, RigProfile, RigProfileId } from '../../api/model3d'

const HUMANOID_RECOMMENDED = ['idle', 'walk', 'wave', 'talk']
const CATEGORY_ORDER = ['Move', 'Gesture', 'Dance', 'Stand', 'Action']
const REFUSALS = new Set(['hands_stuck', 'arms_raised', 'turned', 'single_leg', 'legs_too_short', 'asymmetry', 'not_upright', 'degenerate'])
const WARNINGS = new Set(['arms_steep', 'short_legs', 'short_arms', 'neck_not_found', 'facing_back', 'on_a_base'])
export const DEFAULT_BPM = 120

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

/** Humanoid clips in display groups, known categories first. */
export function clipGroups(animations: RigAnimation[]): { category: string; clips: RigAnimation[] }[] {
  const groups = new Map<string, RigAnimation[]>()
  for (const animation of animations) {
    const category = animation.category || 'Other'
    groups.set(category, [...(groups.get(category) ?? []), animation])
  }
  const rank = (category: string) => {
    const index = CATEGORY_ORDER.indexOf(category)
    return index === -1 ? CATEGORY_ORDER.length : index
  }
  return [...groups.entries()]
    .sort((left, right) => rank(left[0]) - rank(right[0]))
    .map(([category, clips]) => ({ category, clips }))
}

/** Preview files: humanoid clips have their own, since ids overlap the procedural ones. */
export function previewAsset(engineId: string, animationId: string): string {
  return engineId === 'humanoid' ? `humanoid-${animationId}` : `animation-${animationId}`
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

/** The i18n key that explains why a mesh was refused, or null when the error is something else. */
export function refusalKey(job: Pick<RigJob, 'error_code' | 'error_reason'> | null): string | null {
  if (job?.error_code !== 'not_humanoid' || !job.error_reason || !REFUSALS.has(job.error_reason)) return null
  return `rig.refusal.${job.error_reason}`
}

export function warningKeys(warnings: string[] | undefined): string[] {
  return (warnings ?? []).filter(code => WARNINGS.has(code)).map(code => `rig.humanoidWarning.${code}`)
}

export function clampBpm(value: number): number {
  if (!Number.isFinite(value)) return DEFAULT_BPM
  return Math.min(180, Math.max(60, Math.round(value)))
}

export function rigJobBody(input: {
  source: string
  engineId: string
  rigProfileId: RigProfileId
  clips: string[]
  bpm: number
  spineJoints: number
  axisMode: 'auto' | 'x' | 'y' | 'z'
  weightFalloff: number
}): {
  source: string
  engine: string
  rig_profile: RigProfileId
  animations: string[]
  animation_bpm?: number
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
  if (input.engineId === 'humanoid') return { ...body, animation_bpm: clampBpm(input.bpm) }
  return {
    ...body,
    spine_joints: input.spineJoints,
    axis_mode: input.axisMode,
    weight_falloff: input.weightFalloff,
  }
}

/** A short, human file label for a rig in the picker. */
export function rigLabel(name: string): string {
  return name.replace(/\.glb$/i, '').replace(/^\d{4}-\d{2}-\d{2}-\d{2}h\d{2}m\d{2}s_/, '').replace(/^rigged_/, '')
}

/** A GLB the rig panel may offer as a source: not already rigged here, nor a clip copy from "add animations". */
export function isRigSource(name: string): boolean {
  return /\.glb$/i.test(name) && !name.includes('_rigged_') && !/^humanoid-.+-[0-9a-f]{16}\.glb$/i.test(name)
}
