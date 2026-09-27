import { MOBILE_CAMERA, scaleEyeForMobile } from './camera.ts'
import type { Scene3DCamera, Scene3DDocument, Vec3 } from './types.ts'

export type Scene3DFrameFormat = 'landscape' | 'portrait'

export const SCENE3D_FRAME_FORMATS: Record<Scene3DFrameFormat, { width: number; height: number }> = {
  landscape: { width: 1280, height: 720 },
  portrait: { width: 720, height: 1280 },
}

export function scene3dFrameFormat(width: number, height: number): Scene3DFrameFormat {
  return height > width ? 'portrait' : 'landscape'
}

function scaleLateral(value: Vec3): Vec3 {
  return [value[0] * MOBILE_CAMERA.lateral, value[1], value[2] * MOBILE_CAMERA.lateral]
}

function unscaleLateral(value: Vec3): Vec3 {
  return [value[0] / MOBILE_CAMERA.lateral, value[1], value[2] / MOBILE_CAMERA.lateral]
}

export function toPortraitCamera(camera: Scene3DCamera): Scene3DCamera {
  if (camera.frameFormat === 'portrait') return structuredClone(camera)
  const next = structuredClone(camera)
  next.fov = Math.min(78, Math.max(28, next.fov * MOBILE_CAMERA.fovScale))
  next.eye = scaleEyeForMobile(next.eye, next.look)
  if (next.orbitRadius) next.orbitRadius *= MOBILE_CAMERA.distance
  if (next.orbitHeight != null) next.orbitHeight *= MOBILE_CAMERA.orbitHeight
  if (next.eyeOffset) {
    next.eyeOffset = [
      next.eyeOffset[0] * MOBILE_CAMERA.lateral,
      next.eyeOffset[1],
      next.eyeOffset[2] * MOBILE_CAMERA.distance,
    ]
  }
  if (next.targetOffset) next.targetOffset = scaleLateral(next.targetOffset)
  if (next.framing) {
    next.framing = {
      ...next.framing,
      from: scaleLateral(next.framing.from),
      to: scaleLateral(next.framing.to),
    }
    if (next.framing.lookFrom) next.framing.lookFrom = scaleLateral(next.framing.lookFrom)
    else delete next.framing.lookFrom
    if (next.framing.lookTo) next.framing.lookTo = scaleLateral(next.framing.lookTo)
    else delete next.framing.lookTo
  }
  next.frameFormat = 'portrait'
  return next
}

export function fromPortraitCamera(camera: Scene3DCamera): Scene3DCamera {
  const next = structuredClone(camera)
  next.fov = Math.min(78, Math.max(28, next.fov / MOBILE_CAMERA.fovScale))
  next.eye = scaleEyeForMobile(next.eye, next.look, true)
  if (next.orbitRadius) next.orbitRadius /= MOBILE_CAMERA.distance
  if (next.orbitHeight != null) next.orbitHeight /= MOBILE_CAMERA.orbitHeight
  if (next.eyeOffset) {
    next.eyeOffset = [
      next.eyeOffset[0] / MOBILE_CAMERA.lateral,
      next.eyeOffset[1],
      next.eyeOffset[2] / MOBILE_CAMERA.distance,
    ]
  }
  if (next.targetOffset) next.targetOffset = unscaleLateral(next.targetOffset)
  if (next.framing) {
    next.framing = {
      ...next.framing,
      from: unscaleLateral(next.framing.from),
      to: unscaleLateral(next.framing.to),
    }
    if (next.framing.lookFrom) next.framing.lookFrom = unscaleLateral(next.framing.lookFrom)
    else delete next.framing.lookFrom
    if (next.framing.lookTo) next.framing.lookTo = unscaleLateral(next.framing.lookTo)
    else delete next.framing.lookTo
  }
  delete next.frameFormat
  return next
}

export function applyFrameFormat(document: Scene3DDocument, format: Scene3DFrameFormat): Scene3DDocument {
  const size = SCENE3D_FRAME_FORMATS[format]
  const current = scene3dFrameFormat(document.width, document.height)
  let camera = document.camera
  if (format === 'portrait' && current !== 'portrait') camera = toPortraitCamera(camera)
  else if (format === 'landscape' && current === 'portrait') camera = fromPortraitCamera(camera)
  return { ...document, width: size.width, height: size.height, camera }
}

export function adaptAuthoredCameraToFrame(camera: Scene3DCamera, width: number, height: number): Scene3DCamera {
  return scene3dFrameFormat(width, height) === 'portrait' ? toPortraitCamera(camera) : camera
}
