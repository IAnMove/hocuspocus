import type { Scene3DCamera, Scene3DSlot, Vec3 } from './types.ts'

export function vecAdd(a: Vec3, b: Vec3): Vec3 {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
}

export function vecSub(a: Vec3, b: Vec3): Vec3 {
  return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
}

export function vecScale(a: Vec3, s: number): Vec3 {
  return [a[0] * s, a[1] * s, a[2] * s]
}

export function vecDot(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

export function vecCross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

export function vecLength(a: Vec3): number {
  return Math.hypot(a[0], a[1], a[2])
}

export function vecNormalize(a: Vec3): Vec3 {
  const len = vecLength(a)
  if (len < 1e-8) return [0, 1, 0]
  return vecScale(a, 1 / len)
}

export function lerp3(a: Vec3, b: Vec3, t: number): Vec3 {
  return [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ]
}

export function unitProgress(sceneSeconds: number, duration: number): number {
  const span = duration > 1e-6 ? duration : 1
  const u = Math.min(1, Math.max(0, sceneSeconds / span))
  return u * u * (3 - 2 * u)
}

/** Landscape-authored cameras are adapted with these invertible scales for 9:16. */
export const MOBILE_CAMERA = {
  fovScale: 1.22,
  distance: 1.2,
  extraY: 0.14,
  lateral: 0.82,
  orbitHeight: 1.08,
} as const

const MOBILE_RUNTIME_FAMILIES = new Set(['chase', 'hood', 'wing', 'front', 'side', 'pursuit'])

export function scaleEyeForMobile(eye: Vec3, look: Vec3, invert = false): Vec3 {
  if (invert) {
    const delta: Vec3 = [eye[0] - look[0], eye[1] - look[1] - MOBILE_CAMERA.extraY, eye[2] - look[2]]
    return [
      look[0] + delta[0] / MOBILE_CAMERA.distance,
      look[1] + delta[1] / MOBILE_CAMERA.distance,
      look[2] + delta[2] / MOBILE_CAMERA.distance,
    ]
  }
  const delta = vecSub(eye, look)
  return [
    look[0] + delta[0] * MOBILE_CAMERA.distance,
    look[1] + delta[1] * MOBILE_CAMERA.distance + MOBILE_CAMERA.extraY,
    look[2] + delta[2] * MOBILE_CAMERA.distance,
  ]
}

function mobileRuntimeEye(camera: Scene3DCamera, eye: Vec3, look: Vec3): Vec3 {
  if (camera.frameFormat !== 'portrait' || camera.eyeOffset || !MOBILE_RUNTIME_FAMILIES.has(camera.family)) return eye
  return scaleEyeForMobile(eye, look)
}

export function orbitEye(look: Vec3, radius: number, height: number, azimuthRad: number): Vec3 {
  const r = Number.isFinite(radius) && radius > 0 ? radius : 4
  const h = Number.isFinite(height) ? height : 1.6
  return [
    look[0] + Math.sin(azimuthRad) * r,
    look[1] + h,
    look[2] + Math.cos(azimuthRad) * r,
  ]
}

function slotLook(slots: readonly Scene3DSlot[], id: Scene3DSlot['slot'], fallback: Vec3): Vec3 {
  const found = slots.find(slot => slot.slot === id)
  if (!found) return fallback
  return [found.position[0], found.position[1] + 1.1, found.position[2]]
}

export function cameraLookAtTime(
  camera: Scene3DCamera,
  sceneSeconds: number,
  duration: number,
  slots: readonly Scene3DSlot[] = [],
): Vec3 {
  if (camera.family === 'chase' || camera.family === 'hood' || camera.family === 'wing') {
    return camera.family === 'hood' ? [0, 0.82, -14] : [0, 0.7, -0.55]
  }
  if (camera.family === 'follow' || camera.family === 'pursuit' || camera.family === 'side' || camera.family === 'front') {
    return vecAdd(slotLook(slots, 'subject_1', camera.look), camera.targetOffset ?? [0, 0, 0])
  }
  if (camera.family === 'encounter') {
    const a = slotLook(slots, 'subject_1', camera.look)
    const b = slotLook(slots, 'subject_2', camera.look)
    return lerp3(a, b, 0.5)
  }
  if (camera.family === 'orbit' || camera.family === 'product' || camera.family === 'musical') {
    return slotLook(slots, 'subject_1', camera.look)
  }
  void sceneSeconds
  void duration
  return camera.look
}

export function cameraEyeAtTime(
  camera: Scene3DCamera,
  sceneSeconds: number,
  duration: number,
  slots: readonly Scene3DSlot[] = [],
): Vec3 {
  const s = unitProgress(sceneSeconds, duration)
  const look = cameraLookAtTime(camera, sceneSeconds, duration, slots)
  if (camera.eyeOffset && ['follow', 'pursuit', 'side', 'front'].includes(camera.family)) return vecAdd(look, camera.eyeOffset)
  const radius = camera.orbitRadius ?? 4.2
  const height = camera.orbitHeight ?? 1.6
  const turns = Number.isFinite(camera.orbitTurns) ? camera.orbitTurns! : 1
  if (camera.family === 'orbit' || camera.family === 'product' || camera.family === 'musical') {
    const productHeight = camera.family === 'product' ? Math.min(height, 1.15) : height
    const musicalTurns = camera.family === 'musical' ? turns * 2 : turns
    return orbitEye(look, radius, productHeight, s * musicalTurns * Math.PI * 2)
  }
  if (camera.family === 'chase') {
    const sway = Math.sin(sceneSeconds * 1.35) * 0.16
    return mobileRuntimeEye(camera, [0.28 + sway, 1.18, 5.45], look)
  }
  if (camera.family === 'hood') {
    const bump = Math.sin(sceneSeconds * 10) * 0.03
    return mobileRuntimeEye(camera, [0, 1.04 + bump, -0.85], look)
  }
  if (camera.family === 'wing') {
    return mobileRuntimeEye(camera, [5.15, 0.95, 1.65], look)
  }
  if (camera.family === 'front') {
    return mobileRuntimeEye(camera, [look[0], look[1] - 0.08, look[2] + 4.05], look)
  }
  if (camera.family === 'side') {
    return mobileRuntimeEye(camera, [look[0], look[1] - 0.18, look[2] + 3.55], look)
  }
  if (camera.family === 'follow') {
    return [look[0], look[1] + 0.35, look[2] + radius]
  }
  if (camera.family === 'pursuit') {
    return mobileRuntimeEye(camera, [look[0] - 2.1, look[1] + 0.15, look[2] + 2.8], look)
  }
  if (camera.family === 'reveal') {
    return lerp3([camera.eye[0], camera.eye[1] - 1.35, camera.eye[2] + 1.1], camera.eye, s)
  }
  if (camera.family === 'encounter') {
    return lerp3(vecAdd(camera.eye, [-1.6, 0.1, 0.4]), camera.eye, s)
  }
  if (camera.family === 'establishment') {
    return lerp3(vecAdd(camera.eye, [0, 0.55, 2.2]), camera.eye, s)
  }
  return camera.eye
}

export function projectPoint(
  point: Vec3,
  eye: Vec3,
  look: Vec3,
  fovDeg: number,
  aspect: number,
): { x: number; y: number; depth: number } | null {
  const forward = vecNormalize(vecSub(look, eye))
  const worldUp: Vec3 = [0, 1, 0]
  let right = vecCross(forward, worldUp)
  if (vecLength(right) < 1e-6) right = [1, 0, 0]
  right = vecNormalize(right)
  const up = vecNormalize(vecCross(right, forward))
  const rel = vecSub(point, eye)
  const camX = vecDot(rel, right)
  const camY = vecDot(rel, up)
  const camZ = vecDot(rel, forward)
  if (camZ <= 1e-4) return null
  const fov = (Number.isFinite(fovDeg) && fovDeg > 1 ? fovDeg : 50) * Math.PI / 180
  const f = 1 / Math.tan(fov / 2)
  const ndcX = (camX * f) / (aspect * camZ)
  const ndcY = (camY * f) / camZ
  return { x: (ndcX + 1) / 2, y: 1 - (ndcY + 1) / 2, depth: camZ }
}
