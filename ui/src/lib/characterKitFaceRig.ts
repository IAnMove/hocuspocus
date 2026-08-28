import type { CharacterKit, CharacterKitAsset, CharacterKitReviewState, CharacterMouthState } from './characterKit'

export const CHARACTER_FACE_RIG_STATES = ['closed', 'small', 'wide', 'round', 'blink'] as const
export type CharacterKitFaceRigState = typeof CHARACTER_FACE_RIG_STATES[number]

export interface FaceRigGenerationRequest {
  state: CharacterKitFaceRigState
  prompt: string
  poseId: string
  reference: string
}

export interface FaceRigValidation {
  poseId: string
  pose: CharacterKitAsset
}

export interface CharacterKitAlphaMetrics {
  pixelCount: number
  transparentRatio: number
  translucentRatio: number
  opaqueRatio: number
  status: 'transparent' | 'opaque' | 'unknown'
}

export interface FaceRigProvenance {
  method: 'character-kit-face-rig'
  state: CharacterKitFaceRigState
  poseId: string
  reference: string
  prompt: string
  [key: string]: unknown
}

const MOUTH_STATES = new Set<CharacterMouthState>(['closed', 'small', 'wide', 'round'])
const MATERIAL_ALPHA_RATIO = .01

/** Classify an RGBA buffer without guessing when its shape/content is invalid. */
export function classifyCharacterKitAlpha(rgba: Uint8ClampedArray): CharacterKitAlphaMetrics {
  const invalid = { pixelCount: 0, transparentRatio: 0, translucentRatio: 0, opaqueRatio: 0, status: 'unknown' as const }
  if (!(rgba instanceof Uint8ClampedArray) || rgba.length === 0 || rgba.length % 4 !== 0) return invalid
  let transparent = 0
  let translucent = 0
  let opaque = 0
  for (let index = 3; index < rgba.length; index += 4) {
    const alpha = rgba[index]
    if (alpha < 250) {
      transparent++
      if (alpha > 0) translucent++
    }
    if (alpha === 255) opaque++
  }
  const pixelCount = rgba.length / 4
  const transparentRatio = transparent / pixelCount
  const translucentRatio = translucent / pixelCount
  const opaqueRatio = opaque / pixelCount
  return {
    pixelCount,
    transparentRatio,
    translucentRatio,
    opaqueRatio,
    status: transparentRatio >= MATERIAL_ALPHA_RATIO ? 'transparent' : opaqueRatio >= 0.99 ? 'opaque' : 'unknown',
  }
}

function poseFor(kit: CharacterKit, poseId: string): CharacterKitAsset | undefined {
  return poseId === 'base' ? kit.base : kit.poses[poseId]
}

/** Require a reviewed, durable pose before Face Rig generation can use it. */
export function validateFaceRigPose(kit: CharacterKit, poseId = 'base'): FaceRigValidation {
  const normalizedPoseId = poseId.trim() || 'base'
  const pose = poseFor(kit, normalizedPoseId)
  if (!pose) throw new Error(`Character Kit “${kit.name}” has no ${normalizedPoseId} pose.`)
  if (pose.reviewState !== 'approved') throw new Error(`Review and approve ${pose.name} before generating Face Rig states.`)
  if (!pose.source || pose.source.startsWith('blob:')) throw new Error('Face Rig requires a persistent pose source.')
  return { poseId: normalizedPoseId, pose }
}

/** Keep prompts neutral and identity-focused; visual direction belongs to the generator. */
export function faceRigPrompt(kit: CharacterKit, state: CharacterKitFaceRigState, description = ''): string {
  if (!CHARACTER_FACE_RIG_STATES.includes(state)) throw new Error(`Unknown Face Rig state: ${state}`)
  const identity = description.trim() || `${kit.name} character`
  const expression = state === 'blink'
    ? 'an eyes overlay sprite with closed eyelids'
    : `a ${state} mouth overlay sprite`
  return `Generate ONLY ${expression} for ${identity}; use the pose as identity and art-style reference; preserve the facial proportions and colors; isolated transparent PNG/WebP overlay, tightly cropped to the facial piece, aligned to the reference; no full character, no head, no body, no skin rectangle, no background, no text, no glow, no shadow, no extra objects.`
}

export function faceRigGenerationRequests(kit: CharacterKit, poseId = 'base', description = ''): FaceRigGenerationRequest[] {
  const { poseId: normalizedPoseId, pose } = validateFaceRigPose(kit, poseId)
  return CHARACTER_FACE_RIG_STATES.map(state => ({
    state,
    prompt: faceRigPrompt(kit, state, description),
    poseId: normalizedPoseId,
    reference: pose.source,
  }))
}

function assetForState(kit: CharacterKit, state: CharacterKitFaceRigState): CharacterKitAsset | undefined {
  return MOUTH_STATES.has(state as CharacterMouthState)
    ? kit.mouth[state as CharacterMouthState]
    : kit.eyes.blink
}

/** Return a new kit with one generated state attached as pending and provenance recorded. */
export function registerGeneratedFaceRigAsset(
  kit: CharacterKit,
  state: CharacterKitFaceRigState,
  asset: CharacterKitAsset,
  provenance: Pick<FaceRigProvenance, 'poseId' | 'reference' | 'prompt'> & Record<string, unknown>,
): CharacterKit {
  if (!CHARACTER_FACE_RIG_STATES.includes(state)) throw new Error(`Unknown Face Rig state: ${state}`)
  if (!asset.source || asset.source.startsWith('blob:')) throw new Error('Generated Face Rig assets need a persistent source.')
  const nextAsset: CharacterKitAsset = { ...asset, reviewState: 'pending', kind: 'overlay' }
  const nextProvenance: FaceRigProvenance = { ...provenance, method: 'character-kit-face-rig', state }
  return {
    ...kit,
    mouth: MOUTH_STATES.has(state as CharacterMouthState) ? { ...kit.mouth, [state]: nextAsset } : kit.mouth,
    eyes: state === 'blink' ? { ...kit.eyes, blink: nextAsset } : kit.eyes,
    provenance: [...kit.provenance, nextProvenance],
    updatedAt: new Date().toISOString(),
  }
}

export interface FaceRigCleanupResult {
  source: string
  filename: string
  original: string
  width: number
  height: number
  alpha: CharacterKitAlphaMetrics
  method: string
  padding: number
  model?: string
}

/** Replace one overlay with a cleaned PNG while keeping it pending for review. */
export function registerCleanedFaceRigAsset(
  kit: CharacterKit,
  state: CharacterKitFaceRigState,
  cleaned: FaceRigCleanupResult,
): CharacterKit {
  if (!CHARACTER_FACE_RIG_STATES.includes(state)) throw new Error(`Unknown Face Rig state: ${state}`)
  const current = assetForState(kit, state)
  if (!current) throw new Error(`Character Kit “${kit.name}” has no generated ${state} asset to clean.`)
  if (!cleaned.source || cleaned.source.startsWith('blob:')) throw new Error('Cleaned Face Rig assets need a persistent source.')
  const nextAsset: CharacterKitAsset = {
    ...current,
    source: cleaned.source,
    kind: 'overlay',
    alphaStatus: cleaned.alpha?.status ?? 'unknown',
    reviewState: 'pending',
  }
  return {
    ...kit,
    mouth: MOUTH_STATES.has(state as CharacterMouthState) ? { ...kit.mouth, [state]: nextAsset } : kit.mouth,
    eyes: state === 'blink' ? { ...kit.eyes, blink: nextAsset } : kit.eyes,
    provenance: [...kit.provenance, {
      method: 'character-kit-face-rig-cleanup',
      state,
      original: cleaned.original,
      source: cleaned.source,
      filename: cleaned.filename,
      cleanupMethod: cleaned.method,
      model: cleaned.model,
      padding: cleaned.padding,
      alphaMetrics: cleaned.alpha,
      width: cleaned.width,
      height: cleaned.height,
    }],
    updatedAt: new Date().toISOString(),
  }
}

/** Change review status without mutating the kit or its nested asset. */
export function setFaceRigReviewState(kit: CharacterKit, state: CharacterKitFaceRigState, reviewState: CharacterKitReviewState): CharacterKit {
  const current = assetForState(kit, state)
  if (!current) throw new Error(`Character Kit “${kit.name}” has no generated ${state} asset.`)
  const next = { ...current, reviewState }
  return {
    ...kit,
    mouth: MOUTH_STATES.has(state as CharacterMouthState) ? { ...kit.mouth, [state]: next } : kit.mouth,
    eyes: state === 'blink' ? { ...kit.eyes, blink: next } : kit.eyes,
    updatedAt: new Date().toISOString(),
  }
}
