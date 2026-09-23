/** Lighting moods for pixel worlds. A world is painted once in palette
 *  indices; changing the palette relights the whole scene, the way hand-made
 *  color-cycling art moves between night, aurora and dawn. */

type Rgb = [number, number, number]

export type PixelPalette = {
  /** Zenith to horizon. */
  sky: [string, string, string]
  moon: string
  stars: string
  /** Distant range body and the rim-light along its ridges. */
  far: [string, string]
  near: [string, string]
  trees: string
  water: string
  aurora: string
  /** 0..1: how strongly curtains of light hang in the sky. */
  auroraAmount: number
  meteor: string
  /** Key light and ambient for 3D actors and props in the world. */
  light: { color: string; intensity: number }
  ambient: { sky: string; ground: string; intensity: number }
}

export const PIXEL_PALETTES = {
  midnight: {
    sky: ['#0b0d24', '#1d1b46', '#3a3165'], moon: '#f1ecc8', stars: '#d9d5ff',
    far: ['#26244d', '#6c69a8'], near: ['#17163a', '#3d3a73'], trees: '#0c0c22', water: '#121433',
    aurora: '#3fe0b0', auroraAmount: .35, meteor: '#ffd9b0',
    light: { color: '#b9b4ff', intensity: .9 }, ambient: { sky: '#3a3470', ground: '#0c0c1c', intensity: .7 },
  },
  aurora: {
    sky: ['#040c1c', '#0e2a3c', '#1d4c58'], moon: '#e6fff4', stars: '#c9fff0',
    far: ['#10283a', '#3c8c8a'], near: ['#0a1a28', '#23545c'], trees: '#050d16', water: '#0a1c28',
    aurora: '#54ffbe', auroraAmount: 1, meteor: '#d6fff0',
    light: { color: '#8fffd8', intensity: 1 }, ambient: { sky: '#1f6a64', ground: '#06121a', intensity: .75 },
  },
  dawn: {
    sky: ['#2b2b5e', '#9b5c8e', '#f3a58c'], moon: '#fff6e2', stars: '#ffe6f0',
    far: ['#6c4a7c', '#f0a0a0'], near: ['#402c58', '#a86a88'], trees: '#221632', water: '#5a3c6c',
    aurora: '#ffb0d0', auroraAmount: .1, meteor: '#fff2d0',
    light: { color: '#ffc4a8', intensity: 1.6 }, ambient: { sky: '#b07aa0', ground: '#2a1a30', intensity: .9 },
  },
  sunset: {
    sky: ['#3a1c4c', '#c04a50', '#ffb050'], moon: '#fff0c0', stars: '#ffd8a0',
    far: ['#7a2c48', '#ff8a5c'], near: ['#4a1a3a', '#b04a4a'], trees: '#240c1c', water: '#6a2438',
    aurora: '#ff9060', auroraAmount: 0, meteor: '#ffe8a0',
    light: { color: '#ffa060', intensity: 2 }, ambient: { sky: '#c0605a', ground: '#2a0c16', intensity: .9 },
  },
  storm: {
    sky: ['#07090f', '#161c28', '#2c3444'], moon: '#c8d4e4', stars: '#8090a8',
    far: ['#1a2230', '#46546c'], near: ['#0f141e', '#2a3444'], trees: '#06080c', water: '#0e141e',
    aurora: '#8aa8ff', auroraAmount: 0, meteor: '#e0e8ff',
    light: { color: '#9aaccc', intensity: .7 }, ambient: { sky: '#2c3648', ground: '#06080c', intensity: .6 },
  },
  eclipse: {
    sky: ['#12030a', '#3c0a1c', '#7a1c24'], moon: '#ff6a3c', stars: '#ffb0a0',
    far: ['#3a0c1c', '#c0303c'], near: ['#20060e', '#6a1424'], trees: '#0e0206', water: '#2a0610',
    aurora: '#ff4060', auroraAmount: .45, meteor: '#ffc080',
    light: { color: '#ff5a40', intensity: 1.2 }, ambient: { sky: '#6a1420', ground: '#0e0206', intensity: .7 },
  },
  vapor: {
    sky: ['#12062c', '#4c1a6c', '#ff5aa8'], moon: '#fff0ff', stars: '#a0f0ff',
    far: ['#2c0c54', '#ff60c0'], near: ['#1c0840', '#5c2ca0'], trees: '#0c0420', water: '#1c0a3c',
    aurora: '#40f0ff', auroraAmount: .6, meteor: '#b0ffff',
    light: { color: '#ff80e0', intensity: 1.4 }, ambient: { sky: '#6a2ca0', ground: '#10062a', intensity: .8 },
  },
  polar: {
    sky: ['#0c1a34', '#3a6a9c', '#b8e0f4'], moon: '#ffffff', stars: '#e0f4ff',
    far: ['#5a7ca4', '#f0f8ff'], near: ['#2c4a70', '#a8c8e4'], trees: '#12223a', water: '#2a4c70',
    aurora: '#70ffd0', auroraAmount: .5, meteor: '#ffffff',
    light: { color: '#dff0ff', intensity: 1.8 }, ambient: { sky: '#8ab4dc', ground: '#1a2c44', intensity: .9 },
  },
} satisfies Record<string, PixelPalette>

export type PixelPaletteId = keyof typeof PIXEL_PALETTES
export const PIXEL_PALETTE_IDS = Object.keys(PIXEL_PALETTES) as PixelPaletteId[]

export function isPixelPaletteId(value: unknown): value is PixelPaletteId {
  return typeof value === 'string' && value in PIXEL_PALETTES
}

export function hexRgb(hex: string): Rgb {
  const value = parseInt(hex.slice(1), 16)
  return [(value >> 16 & 255) / 255, (value >> 8 & 255) / 255, (value & 255) / 255]
}

function rgbHex([r, g, b]: Rgb) {
  return '#' + [r, g, b].map(channel => Math.round(Math.max(0, Math.min(1, channel)) * 255).toString(16).padStart(2, '0')).join('')
}

function mixHex(a: string, b: string, t: number) {
  const x = hexRgb(a), y = hexRgb(b)
  return rgbHex([x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t])
}

/** Blend two moods field by field. */
export function mixPalettes(a: PixelPalette, b: PixelPalette, t: number): PixelPalette {
  const mix = (x: string, y: string) => mixHex(x, y, t)
  const lerp = (x: number, y: number) => x + (y - x) * t
  return {
    sky: [mix(a.sky[0], b.sky[0]), mix(a.sky[1], b.sky[1]), mix(a.sky[2], b.sky[2])],
    moon: mix(a.moon, b.moon), stars: mix(a.stars, b.stars),
    far: [mix(a.far[0], b.far[0]), mix(a.far[1], b.far[1])],
    near: [mix(a.near[0], b.near[0]), mix(a.near[1], b.near[1])],
    trees: mix(a.trees, b.trees), water: mix(a.water, b.water),
    aurora: mix(a.aurora, b.aurora), auroraAmount: lerp(a.auroraAmount, b.auroraAmount), meteor: mix(a.meteor, b.meteor),
    light: { color: mix(a.light.color, b.light.color), intensity: lerp(a.light.intensity, b.light.intensity) },
    ambient: { sky: mix(a.ambient.sky, b.ambient.sky), ground: mix(a.ambient.ground, b.ambient.ground), intensity: lerp(a.ambient.intensity, b.ambient.intensity) },
  }
}

/** The mood at `seconds`: each palette holds, then glides into the next,
 *  looping over the program. */
export function paletteAt(program: readonly PixelPaletteId[], hold: number, seconds: number): PixelPalette {
  const list = program.length ? program : ['midnight' as const]
  if (list.length === 1) return PIXEL_PALETTES[list[0]]
  const step = Math.max(.5, hold)
  const position = Math.max(0, seconds) / step
  const index = Math.floor(position) % list.length
  const local = position - Math.floor(position)
  // Hold for the first 40% of a step, then ease into the next mood.
  const t = local < .4 ? 0 : (1 - Math.cos((local - .4) / .6 * Math.PI)) / 2
  return mixPalettes(PIXEL_PALETTES[list[index]], PIXEL_PALETTES[list[(index + 1) % list.length]], t)
}
