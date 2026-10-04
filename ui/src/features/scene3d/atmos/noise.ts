/** Integer hash in [0, 1). Same inputs always return the same value. */
export function hash01(n: number): number {
  let x = Math.imul(n | 0, 0x45d9f3b)
  x = Math.imul(x ^ (x >>> 16), 0x45d9f3b)
  x = (x ^ (x >>> 16)) >>> 0
  return x / 4294967296
}

export function hash2(ix: number, iz: number, seed: number): number {
  const n = Math.imul(ix | 0, 374761393) ^ Math.imul(iz | 0, 668265263) ^ Math.imul(seed | 0, 1440672139)
  return hash01(n)
}

function fade(t: number): number {
  return t * t * (3 - 2 * t)
}

/** Smooth value noise on the xz plane. */
export function valueNoise(x: number, z: number, seed: number): number {
  const x0 = Math.floor(x)
  const z0 = Math.floor(z)
  const sx = fade(x - x0)
  const sz = fade(z - z0)
  const a = hash2(x0, z0, seed)
  const b = hash2(x0 + 1, z0, seed)
  const c = hash2(x0, z0 + 1, seed)
  const d = hash2(x0 + 1, z0 + 1, seed)
  return a + (b - a) * sx + (c - a) * sz + (a - b - c + d) * sx * sz
}

export function fbm2(x: number, z: number, seed: number): number {
  const a = valueNoise(x, z, seed)
  const b = valueNoise(x * 2.03 + 4.2, z * 2.03, seed + 11)
  return a * 0.65 + b * 0.35
}

/** Value noise that repeats every `period` cells, so a texture built from it tiles without a seam. */
export function tileNoise(x: number, y: number, period: number, seed: number): number {
  const x0 = Math.floor(x)
  const y0 = Math.floor(y)
  const sx = fade(x - x0)
  const sy = fade(y - y0)
  const wrap = (v: number) => ((v % period) + period) % period
  const a = hash2(wrap(x0), wrap(y0), seed)
  const b = hash2(wrap(x0 + 1), wrap(y0), seed)
  const c = hash2(wrap(x0), wrap(y0 + 1), seed)
  const d = hash2(wrap(x0 + 1), wrap(y0 + 1), seed)
  return a + (b - a) * sx + (c - a) * sy + (a - b - c + d) * sx * sy
}
