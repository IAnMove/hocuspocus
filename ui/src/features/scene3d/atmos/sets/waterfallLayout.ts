import { hash2 } from '../noise.ts'
import type { Area } from '../layout.ts'

export const FALLS_X = 0.12
export const SHEET_Z = -2.6
export const LIP_Y = 5.1
/** Water stays blue-green in every palette; the palette's accent only tints the light. */
export const WATER: Record<string, string> = { moss: '#3e8f86', amber: '#4d9a98' }
/** Plunge pool. The subject stands at z = -0.55, so the front edge stays 0.7 m short of it. */
export const POOL = { x: 0.12, z: -2.3, rx: 1.9, rz: 1.05 } as const
export const LEFT_BANK: Area = { x0: -6.2, x1: -1.25, z0: -2.15, z1: 2.4 }
export const RIGHT_BANK: Area = { x0: 1.85, x1: 6.2, z0: -2.15, z1: 2.4 }

export type Boulder = { x: number; y: number; z: number; sx: number; sy: number; sz: number; yaw: number; tone: number; moss: number }
export type PineSpot = { x: number; y: number; z: number; scale: number }

const COLUMNS = 34
const SWEEP = 1.35
const CHANNEL = 1.3

function wallHeight(theta: number, dx: number): number {
  if (Math.abs(dx) < CHANNEL) return LIP_Y
  return 6.6 - 3.6 * Math.min(1, Math.abs(theta) / SWEEP)
}

/** Columns follow a wide ellipse. Next to the channel they sit further back so no rock crosses the water sheet. */
function columnBase(theta: number): { x: number; z: number; dx: number } {
  const x = FALLS_X + 6.4 * Math.sin(theta)
  const dx = x - FALLS_X
  const near = Math.max(0, Math.min(1, (2.6 - Math.abs(dx)) / 1.3))
  const z = -0.2 - 3.4 * Math.cos(theta) - near * 0.55
  return { x, z, dx }
}

function stack(column: number, layer: number, seed: number): Boulder[] {
  const theta = -SWEEP + (2 * SWEEP * column) / (COLUMNS - 1) + (hash2(column, 3 + layer, seed) - 0.5) * 0.05
  const base = columnBase(theta)
  const height = wallHeight(theta, base.dx) + layer * 0.9
  const push = layer * 0.95
  const count = Math.ceil(height / 0.85)
  const boulders: Boulder[] = []
  for (let k = 0; k < count; k += 1) {
    const n = column * 31 + layer * 7 + k
    const size = (0.62 + hash2(n, 11, seed) * 0.55) * (Math.abs(base.dx) < 2.6 ? 0.88 : 1)
    const top = k === count - 1
    boulders.push({
      x: base.x + Math.sin(theta) * push + (hash2(n, 12, seed) - 0.5) * 0.45,
      y: 0.3 + (k * height) / count,
      z: base.z - Math.cos(theta) * push + (hash2(n, 13, seed) - 0.5) * 0.4,
      sx: size * (0.95 + hash2(n, 14, seed) * 0.5),
      sy: size * 0.82,
      sz: size,
      yaw: hash2(n, 15, seed) * Math.PI,
      tone: hash2(n, 16, seed),
      moss: top && layer === 0 ? 0.85 : hash2(n, 17, seed) > 0.86 ? 0.5 : 0,
    })
  }
  return boulders
}

/** Stratified rock amphitheatre: a cleft at the falls, taller walls to the sides, two layers deep. */
export function cliffBoulders(seed: number): Boulder[] {
  const all: Boulder[] = []
  for (let column = 0; column < COLUMNS; column += 1) {
    all.push(...stack(column, 0, seed), ...stack(column, 1, seed))
  }
  return all
}

/** Small rocks around the pool, leaving the camera side mostly open. */
export function poolRocks(seed: number): Boulder[] {
  const rocks: Boulder[] = []
  for (let i = 0; i < 22; i += 1) {
    const angle = (i / 22) * Math.PI * 2 + hash2(i, 21, seed) * 0.2
    if (Math.sin(angle) > 0.3) continue
    const size = 0.22 + hash2(i, 23, seed) * 0.28
    rocks.push({
      x: POOL.x + (POOL.rx + 0.1) * Math.cos(angle),
      y: size * 0.32,
      z: POOL.z + (POOL.rz + 0.08) * Math.sin(angle),
      sx: size * 1.2, sy: size * 0.7, sz: size,
      yaw: hash2(i, 24, seed) * Math.PI,
      tone: hash2(i, 25, seed),
      moss: hash2(i, 26, seed) > 0.6 ? 0.4 : 0,
    })
  }
  return rocks
}

/** Pines on the rim of the walls. Ground pines are scattered separately so they respect the subject's lane. */
export function rimPines(seed: number): PineSpot[] {
  const spots: PineSpot[] = []
  for (let column = 2; column < COLUMNS - 1; column += 3) {
    const theta = -SWEEP + (2 * SWEEP * column) / (COLUMNS - 1)
    const base = columnBase(theta)
    if (Math.abs(base.dx) < 2.2) continue
    const n = column * 5
    spots.push({
      x: base.x + (hash2(n, 31, seed) - 0.5) * 0.5,
      y: wallHeight(theta, base.dx) + 0.6,
      z: base.z - 0.25 + (hash2(n, 32, seed) - 0.5) * 0.4,
      scale: 1.25 + hash2(n, 33, seed) * 0.6,
    })
  }
  return spots
}
