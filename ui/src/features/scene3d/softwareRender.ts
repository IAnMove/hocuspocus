import { atmosEye, atmosFallbackLook, isAtmosDressing } from './atmos/index.ts'
import { cylinderUvOffset, isCylinderBackdrop, wrapUnit } from './backdrop.ts'
import { cameraEyeAtTime, cameraLookAtTime, projectPoint } from './camera.ts'
import { shakeCamera } from './cameraShake.ts'
import { scene3dSlotColor } from './document.ts'
import type { Scene3DDocument, Scene3DLoop } from './types.ts'
import { renderMotionLabSoftware } from './motionlab/software'

export type SoftwareFrame = {
  width: number
  height: number
  pixels: Uint8Array
}

function fillRect(
  frame: SoftwareFrame,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
  rgb: [number, number, number],
) {
  const left = Math.max(0, Math.floor(Math.min(x0, x1)))
  const right = Math.min(frame.width - 1, Math.ceil(Math.max(x0, x1)))
  const top = Math.max(0, Math.floor(Math.min(y0, y1)))
  const bottom = Math.min(frame.height - 1, Math.ceil(Math.max(y0, y1)))
  for (let y = top; y <= bottom; y += 1) {
    for (let x = left; x <= right; x += 1) {
      const i = (y * frame.width + x) * 4
      frame.pixels[i] = rgb[0]
      frame.pixels[i + 1] = rgb[1]
      frame.pixels[i + 2] = rgb[2]
      frame.pixels[i + 3] = 255
    }
  }
}

function fillScrollingWorld(frame: SoftwareFrame, sceneSeconds: number, loop: Scene3DLoop) {
  const offset = cylinderUvOffset(sceneSeconds, loop.speed)
  for (let x = 0; x < frame.width; x += 1) {
    const stripe = Math.floor(wrapUnit(x / frame.width + offset) * 10) % 2
    const rgb: [number, number, number] = stripe ? [70, 88, 110] : [36, 48, 62]
    for (let y = 0; y < frame.height; y += 1) {
      const i = (y * frame.width + x) * 4
      frame.pixels[i] = rgb[0]
      frame.pixels[i + 1] = rgb[1]
      frame.pixels[i + 2] = rgb[2]
      frame.pixels[i + 3] = 255
    }
  }
}

export function renderScene3DSoftware(document: Scene3DDocument, sceneSeconds: number): SoftwareFrame {
  const native = renderMotionLabSoftware(document, sceneSeconds)
  const width = 160
  const height = Math.max(1, Math.round(160 * document.height / Math.max(1, document.width)))
  const pixels = new Uint8Array(width * height * 4)
  pixels.fill(18)
  for (let i = 3; i < pixels.length; i += 4) pixels[i] = 255
  const frame = native ?? { width, height, pixels }
  const cylinder = document.slots.find(isCylinderBackdrop)
  const fallback = isAtmosDressing(document.dressing) ? atmosFallbackLook(document.atmos, document.dressing) : null
  if (native) { /* Native sets already rasterized their geometry and sky. */ }
  else if (cylinder?.loop) fillScrollingWorld(frame, sceneSeconds, cylinder.loop)
  else if (fallback) {
    fillRect(frame, 0, 0, width, height, fallback.sky)
    fillRect(frame, 0, height * 0.62, width, height, fallback.ground)
  } else fillRect(frame, 0, height * 0.62, width, height, [32, 34, 38])
  const rawEye = cameraEyeAtTime(document.camera, sceneSeconds, document.duration, document.slots)
  const posed = fallback ? atmosEye(rawEye, sceneSeconds, document.duration, document.camera.family) : rawEye
  const { eye, look, roll } = shakeCamera(document.camera.shake, sceneSeconds, posed, cameraLookAtTime(document.camera, sceneSeconds, document.duration, document.slots))
  const aspect = width / height
  for (const slot of document.slots) {
    if (slot.media === 'image') continue
    const projected = projectPoint(slot.position, eye, look, document.camera.fov, aspect)
    if (!projected) continue
    const size = Math.max(6, 28 * slot.scale / Math.max(0.4, projected.depth))
    // The camera rolls with the shake, so the picture turns the other way around its centre.
    const dx = (projected.x - 0.5) * width, dy = (projected.y - 0.5) * height
    const cx = width / 2 + dx * Math.cos(roll) - dy * Math.sin(roll)
    const cy = height / 2 + dx * Math.sin(roll) + dy * Math.cos(roll)
    fillRect(frame, cx - size, cy - size * 1.6, cx + size, cy + size * 0.4, scene3dSlotColor(slot.slot))
  }
  return frame
}

export function hashSoftwareFrame(frame: SoftwareFrame): string {
  let hash = 2166136261
  for (let i = 0; i < frame.pixels.length; i += 1) {
    hash ^= frame.pixels[i]
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16).padStart(8, '0')
}
