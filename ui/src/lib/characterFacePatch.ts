import type { CharacterFaceAnchor, CharacterKit, CharacterKitAsset, CharacterMouthState } from './characterKit'
import type { SceneLayer } from '../types'
import { CHARACTER_MOUTH_STATES } from './characterMouthStates'

export type FacePatchRegion = { x: number; y: number; size: number }
export type FacePatchMetadata = {
  version: 1
  poseId: string
  poseSource: string
  variantSource: string
  sourceWidth: number
  sourceHeight: number
  region: FacePatchRegion
  feather: number
  poseSha256: string
  variantSha256: string
  outputSha256: string
}

export const FACE_PATCH_MAX_PIXELS = 4_194_304
const MOUTH_STATES = CHARACTER_MOUTH_STATES
const integer = (value: unknown, min: number, max: number): value is number =>
  typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max

export function validateFacePatchFrame(width: number, height: number): void {
  if (!integer(width, 16, 4096) || !integer(height, 16, 4096) || width * height > FACE_PATCH_MAX_PIXELS) {
    throw new Error('Face patch images must be 16–4096 pixels per side and at most 4 megapixels.')
  }
}

export function validateFacePatchRegion(region: FacePatchRegion, width: number, height: number, feather: number): void {
  validateFacePatchFrame(width, height)
  if (!region || !integer(region.size, 8, 1024) || !integer(region.x, 0, width - region.size) || !integer(region.y, 0, height - region.size)) {
    throw new Error('Place an 8–1024 pixel patch entirely inside the image.')
  }
  if (typeof feather !== 'number' || !Number.isFinite(feather) || feather < 0 || feather > .25) {
    throw new Error('Face patch feather must be between 0 and 0.25.')
  }
}

const persistent = (value: unknown): value is string => typeof value === 'string'
  && value.length > 0 && value.length <= 1200 && value === value.trim()
  && ![...value].some(char => char.charCodeAt(0) < 32) && !/^(?:blob|data):/i.test(value)

const fileSource = (value: unknown): value is string => persistent(value)
  && (/^\/api\/v1\/(?:file|uploads)\//.test(value) ? !value.endsWith('/')
    : !/[\\/:?#]/.test(value) && value !== '.' && value !== '..')
const exactFields = (value: object, fields: string[]) => Object.keys(value).length === fields.length
  && fields.every(field => Object.hasOwn(value, field))

/** Validate imported annotations. Hashes are recorded observations, not authentication. */
export function validateFacePatchMetadata(value: unknown): FacePatchMetadata {
  if (!value || typeof value !== 'object') throw new Error('Invalid face patch metadata.')
  const raw = value as FacePatchMetadata
  if (!exactFields(raw, ['version', 'poseId', 'poseSource', 'variantSource', 'sourceWidth', 'sourceHeight',
    'region', 'feather', 'poseSha256', 'variantSha256', 'outputSha256'])) throw new Error('Invalid face patch metadata fields.')
  if (raw.version !== 1 || typeof raw.poseId !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$/.test(raw.poseId)) {
    throw new Error('Unsupported face patch version or pose.')
  }
  if (!fileSource(raw.poseSource) || !fileSource(raw.variantSource)) throw new Error('Face patches require saved source images.')
  for (const digest of [raw.poseSha256, raw.variantSha256, raw.outputSha256]) {
    if (typeof digest !== 'string' || !/^[a-f0-9]{64}$/.test(digest)) throw new Error('Face patch source hashes are missing or invalid.')
  }
  validateFacePatchRegion(raw.region, raw.sourceWidth, raw.sourceHeight, raw.feather)
  if (!exactFields(raw.region, ['x', 'y', 'size'])) throw new Error('Invalid face patch region fields.')
  return { version: 1, poseId: raw.poseId, poseSource: raw.poseSource, variantSource: raw.variantSource,
    sourceWidth: raw.sourceWidth, sourceHeight: raw.sourceHeight, region: { x: raw.region.x, y: raw.region.y, size: raw.region.size },
    feather: raw.feather, poseSha256: raw.poseSha256, variantSha256: raw.variantSha256, outputSha256: raw.outputSha256 }
}

export function assertFacePatchPose(asset: CharacterKitAsset, poseId: string, poseSource: string): void {
  if (asset.facePatch === undefined) return
  const patch = validateFacePatchMetadata(asset.facePatch)
  if (patch.poseId !== poseId || patch.poseSource !== poseSource) {
    throw new Error('This facial patch belongs to another pose or an earlier image. Prepare it again for this pose.')
  }
}

export function isFacePatchCompatible(asset: CharacterKitAsset | undefined, poseId: string, poseSource?: string): boolean {
  if (!asset) return true
  try { assertFacePatchPose(asset, poseId, poseSource ?? ''); return true } catch { return false }
}

/** The editor uses a square contain box. Do not silently clamp a region onto another facial feature. */
export function facePatchRegionFromAnchor(anchor: CharacterFaceAnchor, width: number, height: number): FacePatchRegion {
  validateFacePatchFrame(width, height)
  if (![anchor.offsetX, anchor.offsetY, anchor.scale, anchor.rotation].every(Number.isFinite) || anchor.rotation !== 0) {
    throw new Error('Use an unrotated, finite mouth box to prepare a facial patch.')
  }
  const edge = Math.max(width, height)
  const size = Math.round(edge * anchor.scale)
  const region = { x: Math.round(width / 2 + edge * anchor.offsetX / 100 - size / 2),
    y: Math.round(height / 2 + edge * anchor.offsetY / 100 - size / 2), size }
  validateFacePatchRegion(region, width, height, .08)
  return region
}

export function facePatchAnchor(region: FacePatchRegion, width: number, height: number): CharacterFaceAnchor {
  validateFacePatchRegion(region, width, height, 0)
  const edge = Math.max(width, height)
  return { offsetX: (region.x + region.size / 2 - width / 2) * 100 / edge,
    offsetY: (region.y + region.size / 2 - height / 2) * 100 / edge,
    scale: region.size / edge, rotation: 0 }
}

/** Fit the original into the scene first, then place a square patch in actual pixels. */
export function facePatchSceneTransform(pose: SceneLayer['transform'], anchor: CharacterFaceAnchor,
  metadata: FacePatchMetadata, viewport: { width: number; height: number }): SceneLayer['transform'] {
  const patch = validateFacePatchMetadata(metadata)
  if (![viewport.width, viewport.height, pose.scale, anchor.scale].every(value => Number.isFinite(value) && value > 0)
    || ![pose.x, pose.y, pose.rotation ?? 0, anchor.offsetX, anchor.offsetY, anchor.rotation].every(Number.isFinite)) {
    throw new Error('A face patch needs positive scene dimensions and pose scale.')
  }
  const fit = Math.min(viewport.width / patch.sourceWidth, viewport.height / patch.sourceHeight) * pose.scale
  const edge = Math.max(patch.sourceWidth, patch.sourceHeight) * fit
  const angle = (pose.rotation ?? 0) * Math.PI / 180
  const dx = anchor.offsetX * edge / 100
  const dy = anchor.offsetY * edge / 100
  return { x: pose.x + (dx * Math.cos(angle) - dy * Math.sin(angle)) * 100 / viewport.width,
    y: pose.y + (dx * Math.sin(angle) + dy * Math.cos(angle)) * 100 / viewport.height,
    scale: anchor.scale * edge / Math.min(viewport.width, viewport.height), opacity: 1,
    rotation: (pose.rotation ?? 0) + anchor.rotation }
}

/** Preserve skin/texture in an opaque centre; feather only the boundary. No inpainting or identity inference. */
export function cropCharacterFacePatch(rgba: Uint8ClampedArray, width: number, height: number, region: FacePatchRegion, feather = .08): Uint8ClampedArray {
  validateFacePatchRegion(region, width, height, feather)
  if (!(rgba instanceof Uint8ClampedArray) || rgba.length !== width * height * 4) throw new Error('Invalid face patch pixel buffer.')
  const { x, y, size } = region
  const result = new Uint8ClampedArray(size * size * 4)
  const blendPixels = Math.max(1, size * feather)
  for (let row = 0; row < size; row++) {
    for (let col = 0; col < size; col++) {
      const source = ((y + row) * width + x + col) * 4
      const target = (row * size + col) * 4
      const distance = Math.min(row, col, size - 1 - row, size - 1 - col)
      const weight = feather === 0 ? 1 : Math.min(1, distance / blendPixels)
      if (weight === 1 && rgba[source + 3] !== 255) throw new Error('The variant must fully cover the mouth region, including its skin or beard.')
      result.set(rgba.subarray(source, source + 3), target)
      result[target + 3] = Math.round(rgba[source + 3] * weight * weight * (3 - 2 * weight))
    }
  }
  return result
}

export function registerCharacterFacePatch(kit: CharacterKit, poseId: string, state: CharacterMouthState, asset: CharacterKitAsset, metadata: FacePatchMetadata): CharacterKit {
  if (!MOUTH_STATES.includes(state)) throw new Error('Choose a mouth state for this patch.')
  const patch = validateFacePatchMetadata(metadata)
  const pose = poseId === 'base' ? kit.base : kit.poses[poseId]
  if (!pose || pose.reviewState !== 'approved') throw new Error('Approve the base pose before preparing a facial patch.')
  assertFacePatchPose({ ...asset, facePatch: patch }, poseId, pose.source)
  if (!persistent(asset.source) || asset.source === pose.source || asset.source === patch.variantSource || asset.id === pose.id) {
    throw new Error('Save the facial patch as its own image; do not reuse the source identity.')
  }
  const anchor = facePatchAnchor(patch.region, patch.sourceWidth, patch.sourceHeight)
  const previous = kit.anchors[poseId]
  return { ...kit,
    mouth: { ...kit.mouth, [state]: { ...asset, kind: 'overlay', reviewState: 'pending', facePatch: patch } },
    anchors: { ...kit.anchors, [poseId]: { ...previous, mouth: previous?.mouth ?? anchor,
      mouthStates: { ...previous?.mouthStates, [state]: anchor } } },
    provenance: [...kit.provenance, { method: 'character-face-patch-v1', state, source: asset.source, ...patch, region: { ...patch.region } }],
    updatedAt: new Date().toISOString() }
}

export function characterFacePatchPrompt(name: string, state: CharacterMouthState): string {
  const expressions = { closed: 'lips closed, resting naturally', small: 'mouth slightly open in a narrow EE speaking shape',
    wide: 'mouth open in a clear AH speaking shape', round: 'lips rounded in an O speaking shape',
    pressed: 'lips firmly pressed shut for M/B/P', medium: 'mouth moderately open for EH',
    pucker: 'lips narrowly puckered for OO/W', bite: 'upper teeth touching the lower lip for F/V',
    tongue: 'tongue tip raised behind the upper teeth for L' }
  if (!Object.hasOwn(expressions, state)) throw new Error('Choose a mouth state for this patch.')
  return `Edit the reference image of ${name}: change ONLY the mouth to ${expressions[state]}. Preserve the exact canvas, head position, facial proportions, eyes, nose, hair, beard texture, lighting, colors, clothing and background. Keep the surrounding skin or beard, not a detached mouth sprite. No reframing, no new pose, no transparency, no extra faces, no text. This is one full-frame expression variant for region replacement, not a new character.`
}
