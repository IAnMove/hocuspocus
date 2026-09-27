import type { CharacterFaceAnchor } from '../../lib/characterKit'
import { faceRigAnchorFromRegion, faceRigRegionFromAnchor, type FaceRigMouthRegion } from '../../lib/characterKitFaceRig'

/** Erasure bounds are rectangular; the reusable sprite still retains its natural aspect ratio. */
export function mouthWipeBox(anchor: CharacterFaceAnchor, aspect = 1): FaceRigMouthRegion {
  const square = faceRigRegionFromAnchor(anchor)
  const width = square.width * Math.min(1, aspect)
  const height = square.height / Math.max(1, aspect)
  return { x: 50 + anchor.offsetX - width / 2, y: 50 + anchor.offsetY - height / 2, width, height }
}

export function resizeMouthWipeBox(region: FaceRigMouthRegion, width: number, height: number) {
  const resized = { ...region, width: Math.max(.5, Math.min(100, width)), height: Math.max(.5, Math.min(100, height)) }
  return { anchor: faceRigAnchorFromRegion(resized), aspect: resized.width / resized.height }
}
