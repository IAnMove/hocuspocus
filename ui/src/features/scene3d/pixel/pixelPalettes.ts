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
  /** Lit windows, lamps and fireflies. */
  windows: string
  /** Key light and ambient for 3D actors and props in the world. */
  light: { color: string; intensity: number }
  ambient: { sky: string; ground: string; intensity: number }
}

export const PIXEL_PALETTES = {
  midnight: {
    sky: ['#0b0d24', '#1d1b46', '#3a3165'], moon: '#f1ecc8', stars: '#d9d5ff',
    far: ['#26244d', '#6c69a8'], near: ['#17163a', '#3d3a73'], trees: '#0c0c22', water: '#121433',
    aurora: '#3fe0b0', auroraAmount: .35, meteor: '#ffd9b0', windows: '#ffd98a',
    light: { color: '#b9b4ff', intensity: .9 }, ambient: { sky: '#3a3470', ground: '#0c0c1c', intensity: .7 },
  },
  aurora: {
    sky: ['#040c1c', '#0e2a3c', '#1d4c58'], moon: '#e6fff4', stars: '#c9fff0',
    far: ['#10283a', '#3c8c8a'], near: ['#0a1a28', '#23545c'], trees: '#050d16', water: '#0a1c28',
    aurora: '#54ffbe', auroraAmount: 1, meteor: '#d6fff0', windows: '#c8ffe4',
    light: { color: '#8fffd8', intensity: 1 }, ambient: { sky: '#1f6a64', ground: '#06121a', intensity: .75 },
  },
  dawn: {
    sky: ['#2b2b5e', '#9b5c8e', '#f3a58c'], moon: '#fff6e2', stars: '#ffe6f0',
    far: ['#6c4a7c', '#f0a0a0'], near: ['#402c58', '#a86a88'], trees: '#221632', water: '#5a3c6c',
    aurora: '#ffb0d0', auroraAmount: .1, meteor: '#fff2d0', windows: '#ffe2b0',
    light: { color: '#ffc4a8', intensity: 1.6 }, ambient: { sky: '#b07aa0', ground: '#2a1a30', intensity: .9 },
  },
  sunset: {
    sky: ['#3a1c4c', '#c04a50', '#ffb050'], moon: '#fff0c0', stars: '#ffd8a0',
    far: ['#7a2c48', '#ff8a5c'], near: ['#4a1a3a', '#b04a4a'], trees: '#240c1c', water: '#6a2438',
    aurora: '#ff9060', auroraAmount: 0, meteor: '#ffe8a0', windows: '#ffd070',
    light: { color: '#ffa060', intensity: 2 }, ambient: { sky: '#c0605a', ground: '#2a0c16', intensity: .9 },
  },
  storm: {
    sky: ['#07090f', '#161c28', '#2c3444'], moon: '#c8d4e4', stars: '#8090a8',
    far: ['#1a2230', '#46546c'], near: ['#0f141e', '#2a3444'], trees: '#06080c', water: '#0e141e',
    aurora: '#8aa8ff', auroraAmount: 0, meteor: '#e0e8ff', windows: '#ffe7a8',
    light: { color: '#9aaccc', intensity: .7 }, ambient: { sky: '#2c3648', ground: '#06080c', intensity: .6 },
  },
  eclipse: {
    sky: ['#12030a', '#3c0a1c', '#7a1c24'], moon: '#ff6a3c', stars: '#ffb0a0',
    far: ['#3a0c1c', '#c0303c'], near: ['#20060e', '#6a1424'], trees: '#0e0206', water: '#2a0610',
    aurora: '#ff4060', auroraAmount: .45, meteor: '#ffc080', windows: '#ff9a5a',
    light: { color: '#ff5a40', intensity: 1.2 }, ambient: { sky: '#6a1420', ground: '#0e0206', intensity: .7 },
  },
  vapor: {
    sky: ['#12062c', '#4c1a6c', '#ff5aa8'], moon: '#fff0ff', stars: '#a0f0ff',
    far: ['#2c0c54', '#ff60c0'], near: ['#1c0840', '#5c2ca0'], trees: '#0c0420', water: '#1c0a3c',
    aurora: '#40f0ff', auroraAmount: .6, meteor: '#b0ffff', windows: '#7ff6ff',
    light: { color: '#ff80e0', intensity: 1.4 }, ambient: { sky: '#6a2ca0', ground: '#10062a', intensity: .8 },
  },
  polar: {
    sky: ['#0c1a34', '#3a6a9c', '#b8e0f4'], moon: '#ffffff', stars: '#e0f4ff',
    far: ['#5a7ca4', '#f0f8ff'], near: ['#2c4a70', '#a8c8e4'], trees: '#12223a', water: '#2a4c70',
    aurora: '#70ffd0', auroraAmount: .5, meteor: '#ffffff', windows: '#fff4c8',
    light: { color: '#dff0ff', intensity: 1.8 }, ambient: { sky: '#8ab4dc', ground: '#1a2c44', intensity: .9 },
  },
  abyss: {
    sky: ['#7ae0e0', '#1a6a8a', '#06203a'], moon: '#eaffff', stars: '#aef6ff',
    far: ['#0e3a4e', '#3a9aa8'], near: ['#08263a', '#2a8a90'], trees: '#041420', water: '#6a6a5a',
    aurora: '#7affe0', auroraAmount: 0, meteor: '#eaffff', windows: '#ffe8a0',
    light: { color: '#7ae0ff', intensity: 1.1 }, ambient: { sky: '#2a8aa0', ground: '#06202a', intensity: .85 },
  },
  lagoon: {
    sky: ['#b8fff0', '#2aa8b8', '#0a4a6a'], moon: '#ffffff', stars: '#e0fff8',
    far: ['#1a6a7a', '#7ae8d8'], near: ['#0e4a5a', '#5ad0c0'], trees: '#06283a', water: '#a89a70',
    aurora: '#aaffee', auroraAmount: 0, meteor: '#ffffff', windows: '#fff0b0',
    light: { color: '#c8fff4', intensity: 1.6 }, ambient: { sky: '#5ad0d0', ground: '#0a3a4a', intensity: 1 },
  },
  brass: {
    sky: ['#0e0a06', '#1a120a', '#2a1c10'], moon: '#f4e4c0', stars: '#f0d890',
    far: ['#6a4418', '#d8a040'], near: ['#a06a24', '#f4c860'], trees: '#120c06', water: '#2a1c10',
    aurora: '#f0c060', auroraAmount: 0, meteor: '#ffffff', windows: '#ffd070',
    light: { color: '#ffd8a0', intensity: 1.3 }, ambient: { sky: '#6a4a2a', ground: '#120c06', intensity: .8 },
  },
  starry: {
    sky: ['#0a1a4a', '#1e3a8a', '#3a5aa8'], moon: '#fff2a0', stars: '#fff8c0',
    far: ['#1a2a5a', '#6a8ad8'], near: ['#14204a', '#3a5aa0'], trees: '#081228', water: '#10204a',
    aurora: '#f8e080', auroraAmount: 0, meteor: '#ffffff', windows: '#ffd060',
    light: { color: '#c8d8ff', intensity: 1.1 }, ambient: { sky: '#3a5aa8', ground: '#0a1430', intensity: .8 },
  },
  grotto: {
    sky: ['#05060c', '#0a0c18', '#10142a'], moon: '#dffcff', stars: '#8affff',
    far: ['#161a2a', '#3a4a6a'], near: ['#0e1120', '#2a3858'], trees: '#05060a', water: '#0a1a2a',
    aurora: '#7af0ff', auroraAmount: 0, meteor: '#ffffff', windows: '#7af0ff',
    light: { color: '#8ae8ff', intensity: 1 }, ambient: { sky: '#2a3a5a', ground: '#05060a', intensity: .7 },
  },
  nave: {
    sky: ['#0c0a10', '#1a1620', '#2a2230'], moon: '#fff0d0', stars: '#fff0d0',
    far: ['#2a2430', '#6a5a60'], near: ['#3a3038', '#8a7470'], trees: '#08060a', water: '#1a1418',
    aurora: '#ffd070', auroraAmount: 0, meteor: '#ffffff', windows: '#ffd070',
    light: { color: '#ffe0b0', intensity: 1.3 }, ambient: { sky: '#5a4a50', ground: '#140e12', intensity: .8 },
  },
  noon: {
    sky: ['#3a6ab8', '#7ab0e0', '#f0e0b8'], moon: '#fffbe8', stars: '#5a8ccc',
    far: ['#a8604a', '#f0b48a'], near: ['#c8904a', '#f5d49a'], trees: '#3a2418', water: '#d8b070',
    aurora: '#aaccff', auroraAmount: 0, meteor: '#ffffff', windows: '#fff0b0',
    light: { color: '#fff4e0', intensity: 2 }, ambient: { sky: '#9ac0e8', ground: '#6a4a30', intensity: 1 },
  },
  neon: {
    sky: ['#07050e', '#150d28', '#3a1a48'], moon: '#ffe8f4', stars: '#c8b8ff',
    far: ['#141426', '#46466a'], near: ['#0e0e1c', '#34345a'], trees: '#050508', water: '#0a0a16',
    aurora: '#ff3aa0', auroraAmount: 0, meteor: '#ffffff', windows: '#ffcf7a',
    light: { color: '#ff7ad8', intensity: 1.1 }, ambient: { sky: '#3a2a6a', ground: '#07050e', intensity: .75 },
  },
  cosmos: {
    sky: ['#04030c', '#0c0a28', '#1c1444'], moon: '#e8e0ff', stars: '#ffffff',
    far: ['#1a4a8a', '#cfe6ff'], near: ['#3a5a4a', '#a8b0d0'], trees: '#05050f', water: '#0a1a3a',
    aurora: '#ff6ac8', auroraAmount: 0, meteor: '#ffffff', windows: '#ffd27a',
    light: { color: '#dfe8ff', intensity: 1.3 }, ambient: { sky: '#2a2a5a', ground: '#05050f', intensity: .7 },
  },
  jungle: {
    sky: ['#2a5a7a', '#6aaab0', '#f0e2b0'], moon: '#fff6d0', stars: '#ffffff',
    far: ['#2a5a4a', '#8ac89a'], near: ['#16402c', '#4a9a64'], trees: '#0c2416', water: '#2a6a6a',
    aurora: '#aaffcc', auroraAmount: 0, meteor: '#ffffff', windows: '#fff0a0',
    light: { color: '#fff0c8', intensity: 1.7 }, ambient: { sky: '#8ac0b0', ground: '#16402c', intensity: 1 },
  },
  sakura: {
    sky: ['#2a2250', '#b86a9a', '#ffc6b0'], moon: '#fff4ea', stars: '#ffe6f0',
    far: ['#5a4a7a', '#f0c0d8'], near: ['#3a2a4a', '#b07a9a'], trees: '#24162a', water: '#6a4a7a',
    aurora: '#ffb0e0', auroraAmount: 0, meteor: '#fff0f6', windows: '#ffcf8a',
    light: { color: '#ffd0dc', intensity: 1.4 }, ambient: { sky: '#b07aa0', ground: '#2a1a30', intensity: .9 },
  },
  alien: {
    sky: ['#0a0620', '#1f2a5c', '#3fb8a8'], moon: '#f0b47a', stars: '#bff6ff',
    far: ['#2a1650', '#c86aff'], near: ['#160a30', '#7a3cc0'], trees: '#0a0418', water: '#123048',
    aurora: '#ff6ad5', auroraAmount: .3, meteor: '#fff0c0', windows: '#7affd2',
    light: { color: '#c8a0ff', intensity: 1.1 }, ambient: { sky: '#3a2a7a', ground: '#0a0418', intensity: .8 },
  },
  forest: {
    sky: ['#050d12', '#10262a', '#27493f'], moon: '#f0f6d8', stars: '#d8ffe0',
    far: ['#12302c', '#4f8a6a'], near: ['#0a1c18', '#2c5a44'], trees: '#030a08', water: '#0c1e1c',
    aurora: '#9cff8a', auroraAmount: .15, meteor: '#e8ffd0', windows: '#e8ff7a',
    light: { color: '#b8ffcc', intensity: .9 }, ambient: { sky: '#2c5a48', ground: '#040a08', intensity: .7 },
  },
  harbor: {
    sky: ['#070b1a', '#1c2548', '#6a4a5a'], moon: '#ffe8c4', stars: '#c8d4ff',
    far: ['#121a34', '#44507c'], near: ['#0a0f22', '#2a3258'], trees: '#05070f', water: '#0c1226',
    aurora: '#6ae0ff', auroraAmount: 0, meteor: '#fff0d0', windows: '#ffc460',
    light: { color: '#ffcf9a', intensity: 1 }, ambient: { sky: '#3a3f6a', ground: '#07091a', intensity: .75 },
  },
  dusk: {
    sky: ['#1c1036', '#8a3c6a', '#ff9a4a'], moon: '#fff2b0', stars: '#ffd8e8',
    far: ['#6a2c52', '#ff9a6a'], near: ['#a04a3a', '#ffc27a'], trees: '#2a0c1c', water: '#c8704a',
    aurora: '#ff80a0', auroraAmount: 0, meteor: '#fff0c0', windows: '#ffe07a',
    light: { color: '#ffb070', intensity: 2 }, ambient: { sky: '#b05a6a', ground: '#3a1420', intensity: .9 },
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
    aurora: mix(a.aurora, b.aurora), auroraAmount: lerp(a.auroraAmount, b.auroraAmount), meteor: mix(a.meteor, b.meteor), windows: mix(a.windows, b.windows),
    light: { color: mix(a.light.color, b.light.color), intensity: lerp(a.light.intensity, b.light.intensity) },
    ambient: { sky: mix(a.ambient.sky, b.ambient.sky), ground: mix(a.ambient.ground, b.ambient.ground), intensity: lerp(a.ambient.intensity, b.ambient.intensity) },
  }
}

/** A lightning flash lights the painted world for an instant: every
 *  surface washes toward the bolt's cold white. */
export function flashPalette(palette: PixelPalette, flash: number): PixelPalette {
  if (flash <= .01) return palette
  const white = { ...palette, sky: ['#dfe6ff', '#dfe6ff', '#dfe6ff'] as [string, string, string], far: ['#c8d2f0', '#ffffff'] as [string, string],
    near: ['#a8b4d8', '#e8eeff'] as [string, string], trees: '#6a7494', water: '#b8c4e8' }
  return mixPalettes(palette, white, Math.min(.45, flash * .3))
}

/** Screens light the painted land around them with what they show. */
export function tintPalette(palette: PixelPalette, color: string, amount: number): PixelPalette {
  if (amount <= .01) return palette
  const lit = { ...palette, far: [color, color] as [string, string], near: [color, color] as [string, string], trees: color, water: color }
  return mixPalettes(palette, lit, Math.min(.22, amount * .14))
}

/** Colours a user changed on one mood; everything else keeps the preset. */
export type PaletteColors = {
  sky0?: string; sky1?: string; sky2?: string; moon?: string; stars?: string; far0?: string; far1?: string
  near0?: string; near1?: string; trees?: string; water?: string; aurora?: string; windows?: string; light?: string
}
export type PaletteOverrides = Partial<Record<PixelPaletteId, PaletteColors>>
export const PALETTE_COLOR_KEYS = ['sky0', 'sky1', 'sky2', 'moon', 'stars', 'far0', 'far1', 'near0', 'near1', 'trees', 'water', 'aurora', 'windows', 'light'] as const

const HEX = /^#[\da-f]{6}$/i

export function parsePaletteOverrides(raw: unknown): PaletteOverrides | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const out: PaletteOverrides = {}
  for (const [id, colors] of Object.entries(raw as Record<string, unknown>)) {
    if (!isPixelPaletteId(id) || !colors || typeof colors !== 'object') continue
    const kept = Object.fromEntries(PALETTE_COLOR_KEYS.flatMap(key => {
      const value = (colors as Record<string, unknown>)[key]
      return typeof value === 'string' && HEX.test(value) ? [[key, value.toLowerCase()]] : []
    })) as PaletteColors
    if (Object.keys(kept).length) out[id] = kept
  }
  return Object.keys(out).length ? out : undefined
}

/** A preset with the user's colours laid over it. */
export function paletteWith(id: PixelPaletteId, colors: PaletteColors | undefined): PixelPalette {
  const base = PIXEL_PALETTES[id]
  if (!colors) return base
  const pick = (key: typeof PALETTE_COLOR_KEYS[number]) => colors[key] ?? paletteColor(base, key)
  return {
    ...base,
    sky: [pick('sky0'), pick('sky1'), pick('sky2')], far: [pick('far0'), pick('far1')], near: [pick('near0'), pick('near1')],
    moon: pick('moon'), stars: pick('stars'), trees: pick('trees'), water: pick('water'), aurora: pick('aurora'), windows: pick('windows'),
    light: { ...base.light, color: pick('light') },
  }
}

/** The colour of one editable slot in a palette, for the colour pickers. */
export function paletteColor(palette: PixelPalette, key: typeof PALETTE_COLOR_KEYS[number]): string {
  const pairs: Record<typeof PALETTE_COLOR_KEYS[number], string> = {
    sky0: palette.sky[0], sky1: palette.sky[1], sky2: palette.sky[2], moon: palette.moon, stars: palette.stars,
    far0: palette.far[0], far1: palette.far[1], near0: palette.near[0], near1: palette.near[1], trees: palette.trees,
    water: palette.water, aurora: palette.aurora, windows: palette.windows, light: palette.light.color,
  }
  return pairs[key]
}

/** The mood at `seconds`: each palette holds, then glides into the next,
 *  looping over the program. */
export function paletteAt(program: readonly PixelPaletteId[], hold: number, seconds: number, overrides?: PaletteOverrides): PixelPalette {
  const list = program.length ? program : ['midnight' as const]
  const mood = (id: PixelPaletteId) => paletteWith(id, overrides?.[id])
  if (list.length === 1) return mood(list[0])
  const step = Math.max(.5, hold)
  const position = Math.max(0, seconds) / step
  const index = Math.floor(position) % list.length
  const local = position - Math.floor(position)
  // Hold for the first 40% of a step, then ease into the next mood.
  const t = local < .4 ? 0 : (1 - Math.cos((local - .4) / .6 * Math.PI)) / 2
  return mixPalettes(mood(list[index]), mood(list[(index + 1) % list.length]), t)
}
