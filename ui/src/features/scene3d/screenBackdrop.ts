import { parseSceneFx, type SceneFx } from '../sceneFx/types'

/** A flat colour plus screen effects, painted as the frame's background: every 3D object,
 * flat cutouts included, stays in front of it. With an environment plate (an image slot with
 * `surface: 'environment'`) the plate is drawn first and the effects over it. Effects use the
 * same cues and painters as `sfx`, so radial `speedlines` here are the anime focus-line
 * backdrop rather than lines over the characters. */
export type ScreenBackdrop = { color: string; sfx: SceneFx[] }

export const SCREEN_BACKDROP_COLOR = '#10141c'

export function parseScreenBackdrop(raw: unknown): ScreenBackdrop | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const value = raw as { color?: unknown; sfx?: unknown }
  const color = typeof value.color === 'string' && /^#[\da-f]{6}$/i.test(value.color) ? value.color : SCREEN_BACKDROP_COLOR
  return { color, sfx: parseSceneFx(value.sfx) }
}

export function screenBackdropField(raw: unknown): { screenBackdrop?: ScreenBackdrop } {
  const screenBackdrop = parseScreenBackdrop(raw)
  return screenBackdrop ? { screenBackdrop } : {}
}
