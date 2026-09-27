import type { KineticText, TextFont } from './types'

export const TEXT_FONT_STACK: Record<TextFont, string> = {
  sans: 'system-ui, sans-serif',
  mono: 'ui-monospace, monospace',
  display: '"Hocus Display", Impact, sans-serif',
  condensed: '"Hocus Condensed", "Arial Narrow", sans-serif',
  serif: '"Hocus Serif", Georgia, serif',
  hand: '"Hocus Hand", cursive',
  marker: '"Hocus Marker", cursive',
}

const CUSTOM_FACE: Partial<Record<TextFont, string>> = {
  display: 'Hocus Display',
  condensed: 'Hocus Condensed',
  serif: 'Hocus Serif',
  hand: 'Hocus Hand',
  marker: 'Hocus Marker',
}

/** Resolve vendored faces before the first headless frame. System faces return immediately. */
export async function ensureTextFonts(texts: readonly Pick<KineticText, 'font'>[] | undefined) {
  if (typeof document === 'undefined' || !document.fonts?.load) return
  const faces = new Set<string>()
  for (const cue of texts ?? []) {
    const face = cue.font ? CUSTOM_FACE[cue.font] : undefined
    if (face) faces.add(face)
  }
  await Promise.all([...faces].map(face => document.fonts.load(`16px "${face}"`).catch(() => undefined)))
  await document.fonts.ready
}
