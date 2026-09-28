import fontCatalog from '../../../../app/shared/fonts.json' with { type: 'json' }
import type { KineticText, TextFont } from './types'

type FontEntry = { kineticRole?: string; stack?: string; family: string; files: string[] }

const kineticFaces = (fontCatalog.entries as FontEntry[]).filter(entry => entry.kineticRole && entry.stack)

export const TEXT_FONT_STACK = Object.fromEntries(
  kineticFaces.map(entry => [entry.kineticRole, entry.stack]),
) as Record<TextFont, string>

const CUSTOM_FACE = Object.fromEntries(
  kineticFaces.filter(entry => entry.files.length > 0).map(entry => [entry.kineticRole, entry.family]),
) as Partial<Record<TextFont, string>>

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
