import { Mesh, MeshBasicMaterial, SRGBColorSpace, type Object3D } from 'three'
import type { Tint } from './directionalPaint'

/** A directional sprite is unlit, so its brightness does not swing with the camera angle; it takes the colour and strength of the
 * scene's key light by this multiplier instead (`lightTint` in directionalSprite.ts; 1, 1, 1 is the picture as drawn). */
export function tintSprite(root: Object3D | undefined, tint: Tint | undefined) {
  if (!tint || !(root instanceof Mesh)) return
  if (root.material instanceof MeshBasicMaterial) root.material.color.setRGB(tint[0], tint[1], tint[2], SRGBColorSpace)
}
