import { validFraming } from './framing'
import type { Scene3DCamera, Scene3DDocument, Scene3DLight, Scene3DSlot } from './types.ts'

const CAMERA_FAMILIES = new Set(['establishment', 'follow', 'orbit', 'reveal', 'encounter', 'pursuit', 'product', 'musical', 'side', 'front', 'chase', 'hood', 'wing'])
const SLOT_ROLES = new Set(['subject_1', 'subject_2', 'prop', 'background'])
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value)
const positive = (value: unknown): value is number => finite(value) && value > 0
const vector = (value: unknown) => Array.isArray(value) && value.length === 3 && value.every(finite)

function validCamera(camera: Scene3DCamera) {
  if (!vector(camera.eye) || !vector(camera.look) || !positive(camera.fov) || camera.fov >= 180) return false
  if (!CAMERA_FAMILIES.has(camera.family)) return false
  if (camera.frameFormat != null && camera.frameFormat !== 'portrait' && camera.frameFormat !== 'landscape') return false
  if (camera.framing != null && !validFraming(camera.framing)) return false
  if ([camera.targetOffset, camera.eyeOffset].some(value => value != null && !vector(value))) return false
  const optionalNumbers = [camera.orbitRadius, camera.orbitHeight, camera.orbitTurns]
  if (!optionalNumbers.every(value => value == null || finite(value))) return false
  return camera.orbitRadius == null || camera.orbitRadius > 0
}

function validLight(light: Scene3DLight) {
  if (!vector(light.direction) || !finite(light.intensity) || typeof light.color !== 'string') return false
  return light.kind === 'directional' && light.intensity >= 0 && Math.hypot(...light.direction) > 0
}

function validClip(clip: Scene3DSlot['clip']) {
  return clip == null || (Number.isInteger(clip.index) && clip.index >= 0 && typeof clip.name === 'string')
}

function validSlot(slot: Scene3DSlot) {
  if (!slot || typeof slot.id !== 'string' || !slot.id) return false
  return vector(slot.position) && positive(slot.scale) && finite(slot.rotationY)
    && SLOT_ROLES.has(slot.slot) && validClip(slot.clip)
}

/** Validate user-imported geometry before it reaches Three or frame allocation. */
export function validScene3DShape(value: Partial<Scene3DDocument>) {
  if (!positive(value.width) || !positive(value.height) || !positive(value.duration) || value.duration > 600) return false
  if (![24, 30, 60].includes(value.fps!)) return false
  if (!value.camera || !value.light || !Array.isArray(value.slots)) return false
  if (!validCamera(value.camera) || !validLight(value.light)) return false
  if (value.camera.framing && !value.slots.some(slot => slot?.id === value.camera!.framing!.targetSlot)) return false
  if (value.slots.length > 64 || !value.slots.every(validSlot)) return false
  return new Set(value.slots.map(slot => slot.id)).size === value.slots.length
}
