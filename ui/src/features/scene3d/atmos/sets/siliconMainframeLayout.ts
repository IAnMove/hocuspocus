import { hash2 } from '../noise.ts'

export type Cabinet = { x: number; z: number; face: number; w: number; h: number; d: number }
export type Reel = { x: number; y: number; z: number; r: number }
export type Drive = { x: number; z: number; w: number; h: number; d: number }
export type Bead = { x: number; y: number; z: number }

const LEFT = [-5.2, -2.85]
const RIGHT = [3.45, 5.8]

export function mainframeCabinets(count: number): Cabinet[] {
  const columns = count <= 8 ? [LEFT[1], RIGHT[0]] : [...LEFT, ...RIGHT]
  const per = Math.max(1, Math.ceil(count / columns.length))
  const cabinets: Cabinet[] = []
  for (const x of columns) {
    if (cabinets.length >= count) break
    const room = Math.min(per, count - cabinets.length)
    for (let row = 0; row < room; row += 1) {
      cabinets.push({
        x,
        z: -7.8 + row * 1.85,
        face: x < 0 ? 1 : -1,
        w: 0.72,
        h: 3.4 + (row % 2) * 0.45,
        d: 1.25,
      })
    }
  }
  return cabinets
}

export function tapeReels(): Reel[] {
  const reels: Reel[] = []
  for (const x of [-6.35, 6.35]) {
    for (const z of [-5.4, -2.7]) {
      reels.push({ x, y: 1.35, z, r: 0.42 })
      reels.push({ x, y: 2.35, z, r: 0.42 })
    }
  }
  return reels
}

export function diskDrives(): Drive[] {
  return [-6.2, 6.2].flatMap(x => [
    { x, z: -0.55, w: 0.7, h: 1.15, d: 0.85 },
    { x, z: 1.15, w: 0.7, h: 0.72, d: 0.85 },
  ])
}

export function cableBeads(): Bead[] {
  const beads: Bead[] = []
  for (let cable = 0; cable < 3; cable += 1) {
    const z = -6.4 + cable * 1.7
    for (let step = 0; step < 18; step += 1) {
      const t = step / 17
      const sag = Math.sin(t * Math.PI) * 1.05
      beads.push({ x: -4.4 + t * 8.8, y: 5.35 - sag, z })
    }
  }
  return beads
}

export function activeCount(total: number, variant: number | undefined): number {
  const amount = typeof variant === 'number' && Number.isFinite(variant) ? variant : 4
  const clamped = Math.min(8, Math.max(0, amount))
  return Math.round((clamped / 8) * total)
}

export function scanRate(time: string): number {
  return time === 'burst' ? 2 : 0.35
}

export function cabinetLit(index: number, total: number, variant: number | undefined, seconds: number, time: string, seed: number): boolean {
  if (index >= activeCount(total, variant)) return false
  if (time === 'burst') {
    const sweep = (seconds * scanRate(time)) % 1
    const pos = total <= 1 ? 0 : index / total
    const delta = Math.abs(pos - sweep)
    return Math.min(delta, 1 - delta) < 0.2
  }
  const phase = hash2(index, 3, seed)
  return (seconds * 0.45 + phase) % 1 < 0.28
}
