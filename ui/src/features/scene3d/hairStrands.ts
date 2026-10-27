/** Strand cards for lofted hair.
 *
 * The lofted body writes its hair as flat curved cards (`blob_hair`) in a primitive named `hair`, with `u` across a lock and
 * `v` from its root (0) to its tip (1). This gives that material a strand map: grey values that multiply the hair colour into
 * streaks and a light seam between strands, and an alpha that narrows each lock to a frayed tip, cut out with `alphaTest`
 * (so it needs no sorting and gets no ink hull). Generated, never loaded: the same pixels everywhere. */
import { ClampToEdgeWrapping, DataTexture, DoubleSide, LinearFilter, NoColorSpace, RGBAFormat, UnsignedByteType } from 'three'
import type { Material, Mesh, MeshStandardMaterial, Object3D } from 'three'

export const STRAND_WIDTH = 128
export const STRAND_HEIGHT = 256
const STRAND = 4

function mulberry32(seed: number) {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/** RGBA pixels, row 0 the root. */
export function hairStrandPixels(): Uint8Array {
  const random = mulberry32(7)
  const strands = Array.from({ length: STRAND_WIDTH / STRAND }, () => ({ reach: 0.72 + random() * 0.28, tone: 0.84 + random() * 0.16, phase: random() * 6.283 }))
  const pixels = new Uint8Array(STRAND_WIDTH * STRAND_HEIGHT * 4)
  for (let y = 0; y < STRAND_HEIGHT; y++) {
    const v = y / (STRAND_HEIGHT - 1)
    const bend = Math.max(0, (v - 0.5) / 0.5)
    const envelope = 1 - 0.8 * bend * bend * (3 - 2 * bend)
    for (let x = 0; x < STRAND_WIDTH; x++) {
      const strand = strands[Math.floor(x / STRAND)]
      const across = Math.abs(2 * (x + 0.5) / STRAND_WIDTH - 1)
      const inside = across <= envelope && v <= strand.reach * (1 - 0.2 * across)
      const seam = x % STRAND === 0 ? 0.8 : 1
      const value = Math.round(255 * Math.min(1, strand.tone * seam * (0.93 + 0.07 * Math.sin(v * 5 + strand.phase))))
      const at = (y * STRAND_WIDTH + x) * 4
      pixels[at] = pixels[at + 1] = pixels[at + 2] = value
      pixels[at + 3] = inside ? 255 : 0
    }
  }
  return pixels
}

let shared: DataTexture | undefined

export function hairStrandTexture(): DataTexture {
  if (!shared) {
    shared = new DataTexture(hairStrandPixels(), STRAND_WIDTH, STRAND_HEIGHT, RGBAFormat, UnsignedByteType)
    shared.colorSpace = NoColorSpace // the greys are multipliers of the hair colour, not a picture
    shared.magFilter = shared.minFilter = LinearFilter
    shared.generateMipmaps = false // mip levels would eat the cut-out edge
    shared.wrapS = shared.wrapT = ClampToEdgeWrapping
    shared.needsUpdate = true
  }
  return shared
}

/** Give the `hair` material of a loaded model its strand map. Only for a mesh that has texture coordinates: hair written
 * before the cards (no `uv`) keeps its plain colour. */
export function applyHairStrands(root: Object3D): void {
  root.traverse(object => {
    const mesh = object as Mesh
    if (!mesh.isMesh || !mesh.geometry.getAttribute('uv')) return
    for (const item of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) {
      const material = item as Material & Partial<MeshStandardMaterial>
      if (!material || material.name !== 'hair' || material.userData.hairStrands || material.userData.atlas) continue   // a hair cap draped from the head picture keeps it
      material.map = hairStrandTexture()
      material.alphaTest = 0.5
      material.side = DoubleSide
      material.userData.hairStrands = true
      material.needsUpdate = true
    }
  })
}
