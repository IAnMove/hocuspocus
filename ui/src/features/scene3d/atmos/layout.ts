import { hash2 } from './noise.ts'
import type { Vec3 } from '../types.ts'

/** Open ground for a character, about 3.5 m in front of the end camera. */
export const CLEARING_SUBJECT: Vec3 = [0.72, 0, -0.55]
export const CLEARING_EYE: Vec3 = [0.08, 1.52, 2.9]
export const CLEARING_LOOK: Vec3 = [0.55, 0.42, -1.2]
export const BACKLIGHT_EYE: Vec3 = [1.55, 1.48, 3.15]
export const BACKLIGHT_LOOK: Vec3 = [-0.05, 0.38, -1.1]

export type Trunk = { x: number; z: number; height: number; radius: number; layer: 1 | 2 | 3; yaw: number }

const CLEAR_RADIUS = 1.4

function blocked(x: number, z: number): boolean {
  const dx = x - CLEARING_SUBJECT[0]
  const dz = z - CLEARING_SUBJECT[2]
  if (dx * dx + dz * dz < CLEAR_RADIUS * CLEAR_RADIUS) return true
  return z > -1.15 && z < 3.5 && x > -1.05 && x < 1.7
}

function ring(layer: 1 | 2 | 3, count: number, seed: number, z0: number, z1: number, x0: number, x1: number): Trunk[] {
  const trunks: Trunk[] = []
  let n = 0
  while (trunks.length < count && n < count * 12) {
    const h = hash2(n, layer, seed)
    const side = hash2(n, layer + 9, seed) > 0.5 ? 1 : -1
    const x = side * (x0 + (x1 - x0) * hash2(n, layer + 3, seed))
    const z = z0 + (z1 - z0) * h
    n += 1
    if (blocked(x, z)) continue
    if (trunks.some(trunk => (trunk.x - x) ** 2 + (trunk.z - z) ** 2 < 1.6)) continue
    const height = (layer === 1 ? 7.5 : layer === 2 ? 10 : 13) + h * 4
    trunks.push({
      x, z, height,
      radius: (layer === 3 ? 0.22 : 0.34) + hash2(n, layer + 5, seed) * 0.16,
      layer,
      yaw: hash2(n, layer + 7, seed) * Math.PI,
    })
  }
  return trunks
}

export function clearingTrunks(seed: number): Trunk[] {
  return [
    ...ring(1, 8, seed, -8.5, -1.6, 1.7, 4.4),
    ...ring(2, 12, seed, -18, -7, 3.2, 8.5),
    ...ring(3, 14, seed, -36, -15, 4.5, 13),
  ]
}

export function subjectIsClear(trunks: readonly Trunk[]): boolean {
  return trunks.every(trunk => {
    const dx = trunk.x - CLEARING_SUBJECT[0]
    const dz = trunk.z - CLEARING_SUBJECT[2]
    return dx * dx + dz * dz >= CLEAR_RADIUS * CLEAR_RADIUS
  })
}
