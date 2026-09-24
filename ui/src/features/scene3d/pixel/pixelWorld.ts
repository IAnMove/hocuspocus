import { isPixelPaletteId, parsePaletteOverrides, type PaletteOverrides, type PixelPaletteId } from './pixelPalettes'
import { parsePixelScene, type PixelScene } from './pixelScene'

/** How a scene is lit and pixelated: a program of palettes it glides
 *  through, how long each holds, and the pixel look over the whole frame. */
export type PixelWorld = {
  palettes: PixelPaletteId[]
  /** Seconds each palette holds before gliding into the next. */
  hold: number
  /** Shooting stars, 0 (none) to 1 (about one every seven seconds). */
  meteors: number
  /** Screen pixels per art pixel; 1 leaves the frame unpixelated. */
  pixelSize: number
  /** Colour levels per channel. */
  levels: number
  /** Ordered dithering between levels, 0..1. */
  dither: number
  /** How much light TV and monitor screens throw on the room, 0..2. */
  screenGlow: number
  /** Changes to the world's layout: sun or moon, ranges, trees, water... */
  scene?: Partial<PixelScene>
  /** Colours changed on individual moods. */
  colors?: PaletteOverrides
}

const bounded = (value: unknown, fallback: number, min: number, max: number) =>
  typeof value === 'number' && Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback

export const defaultPixelWorld = (): PixelWorld => ({
  palettes: ['midnight', 'aurora', 'dawn'], hold: 6, meteors: .5, pixelSize: 3, levels: 48, dither: .35, screenGlow: 1,
})

function optional<K extends string, T>(key: K, value: T | undefined): Partial<Record<K, T>> {
  return value === undefined ? {} : { [key]: value } as Partial<Record<K, T>>
}

export function parsePixelWorld(raw: unknown): PixelWorld | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const value = raw as Partial<PixelWorld>, fallback = defaultPixelWorld()
  const palettes = Array.isArray(value.palettes) ? value.palettes.filter(isPixelPaletteId).slice(0, 8) : []
  return {
    palettes: palettes.length ? palettes : fallback.palettes,
    hold: bounded(value.hold, fallback.hold, .5, 120),
    meteors: bounded(value.meteors, fallback.meteors, 0, 1),
    pixelSize: Math.round(bounded(value.pixelSize, fallback.pixelSize, 1, 8)),
    levels: Math.round(bounded(value.levels, fallback.levels, 4, 64)),
    dither: bounded(value.dither, fallback.dither, 0, 1),
    screenGlow: bounded(value.screenGlow, fallback.screenGlow, 0, 2),
    ...optional('scene', parsePixelScene(value.scene)),
    ...optional('colors', parsePaletteOverrides(value.colors)),
  }
}
