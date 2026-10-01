import { hash2 } from '../noise.ts'
import { scatter, type Area, type Trunk } from '../layout.ts'

export type Chip = { x: number; z: number; yaw: number; w: number; d: number; h: number }
export type Tower = { x: number; z: number; r: number; h: number }
export type Bridge = { x: number; z: number; yaw: number; length: number }
export type Fin = { x: number; z: number; y: number; sx: number; sy: number; sz: number }

const LEFT: Area = { x0: -7.4, x1: -2.35, z0: -8.4, z1: 1.6 }
const RIGHT: Area = { x0: 2.75, x1: 7.6, z0: -8.4, z1: 1.6 }
const BACK: Area = { x0: -6.2, x1: 6.2, z0: -9.2, z1: -2.6 }
const RIDGE_Z = -8.7

function trunksOf(spots: Array<[number, number]>, radius: number): Trunk[] {
  return spots.map(([x, z]) => ({ x, z, height: 1, radius, layer: 1 as const, yaw: 0 }))
}

function chipFrom(spot: [number, number], index: number, seed: number): Chip {
  return {
    x: spot[0],
    z: spot[1],
    yaw: (hash2(index, 4, seed) - 0.5) * 0.5,
    w: 0.9 + hash2(index, 5, seed) * 0.45,
    d: 0.62 + hash2(index, 6, seed) * 0.28,
    h: 3.2 + hash2(index, 7, seed) * 5.2,
  }
}

/** Local +x / +z into world xz. Matches Object3D rotation.y (local +x → (cos θ, −sin θ)). */
export function worldOffset(yaw: number, lx: number, lz: number): [number, number] {
  const c = Math.cos(yaw)
  const s = Math.sin(yaw)
  return [lx * c + lz * s, -lx * s + lz * c]
}

export function circuitChips(seed: number, count: number): Chip[] {
  const half = Math.ceil(count / 2)
  const left = scatter(half, seed, 11, [], LEFT, 0.2)
  const right = scatter(Math.max(0, count - half), seed, 17, trunksOf(left, 0.85), RIGHT, 0.2)
  return [...left, ...right].map((spot, index) => chipFrom(spot, index, seed))
}

function ridgeTrunks(): Trunk[] {
  const trunks: Trunk[] = []
  for (let index = 0; index < 8; index += 1) {
    trunks.push({ x: -2.4 + index * 0.68, z: RIDGE_Z, height: 2, radius: 0.55, layer: 1, yaw: 0 })
  }
  return trunks
}

export function circuitTowers(seed: number, count: number, chips: readonly Chip[]): Tower[] {
  const taken = [...trunksOf(chips.map(chip => [chip.x, chip.z]), 0.9), ...ridgeTrunks()]
  const spots = scatter(count, seed, 23, taken, BACK, 0.55)
  return spots.map(([x, z], index) => ({
    x,
    z,
    r: 0.28 + hash2(index, 8, seed) * 0.22,
    h: 2.1 + hash2(index, 9, seed) * 2.8,
  }))
}

export function circuitBridges(seed: number, count: number, chips: readonly Chip[], towers: readonly Tower[]): Bridge[] {
  const taken = trunksOf(
    [...chips.map(chip => [chip.x, chip.z] as [number, number]), ...towers.map(tower => [tower.x, tower.z] as [number, number])],
    0.55,
  )
  const spots = scatter(count, seed, 29, taken, { x0: -6.4, x1: 6.4, z0: -7.6, z1: -3.4 }, 0.35)
  return spots.map(([x, z], index) => ({
    x,
    z,
    yaw: hash2(index, 12, seed) > 0.5 ? 0 : Math.PI / 2,
    length: 1.5 + hash2(index, 13, seed) * 1.1,
  }))
}

export function heatsinkFins(): Fin[] {
  const fins: Fin[] = []
  for (let index = 0; index < 8; index += 1) {
    fins.push({
      x: -2.4 + index * 0.68,
      z: RIDGE_Z,
      y: 1.55,
      sx: 0.1,
      sy: 2.4,
      sz: 1.25,
    })
  }
  return fins
}

export function activeCount(total: number, variant: number | undefined): number {
  const amount = typeof variant === 'number' && Number.isFinite(variant) ? variant : 4
  const clamped = Math.min(8, Math.max(0, amount))
  return Math.round((clamped / 8) * total)
}

/** Idle is a slow sweep. Compute locks the sweep to 120 BPM (2 Hz). */
export function pulseRate(time: string): number {
  return time === 'compute' ? 2 : 0.45
}

export function ledLit(index: number, total: number, variant: number | undefined, seconds: number, time: string, seed: number): boolean {
  if (index >= activeCount(total, variant)) return false
  const phase = hash2(index, 3, seed)
  const duty = time === 'compute' ? 0.62 : 0.28
  const cycle = (seconds * pulseRate(time) + phase) % 1
  return cycle < duty
}
