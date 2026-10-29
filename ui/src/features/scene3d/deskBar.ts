/** Stateless controls that leave the one-row desk bar, least important first. */
export type DeskBarOverflow = 'expand' | 'history'

/**
 * Which controls leave the row at this content width, in pixels.
 * Expand goes first, then undo and redo. The render picker stays mounted
 * because it owns the level. The name, open, save and export stay.
 */
export function deskBarOverflow(width: number): DeskBarOverflow[] {
  if (width >= 1000) return []
  if (width >= 720) return ['expand']
  return ['expand', 'history']
}
