import { fbm2 } from './noise.ts'

export type WindSample = { x: number; z: number; bend: number }

/** One wind field. Grass, hanging leaves and motes all read this. */
export function windAt(x: number, z: number, seconds: number, speed: number, gust: number, seed: number): WindSample {
  const t = seconds * Math.max(0, speed)
  const broad = fbm2(x * 0.045 + t * 0.15, z * 0.045, seed)
  const fine = fbm2(x * 0.12 - t * 0.22, z * 0.1, seed + 19)
  const angle = (broad - 0.5) * 1.1
  const mag = 0.25 + fine * (0.35 + Math.max(0, gust))
  return {
    x: Math.cos(angle) * mag,
    z: Math.sin(angle) * mag * 0.4,
    bend: (broad - 0.42) * (0.55 + gust),
  }
}
