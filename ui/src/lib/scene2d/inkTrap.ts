// Colored type reserves the black plate with a stroke of 5% of the font size.
// Off unless the cue sets trap or the frame is on the riso press.

export const INK_TRAP_RATIO = 0.05
export const INK_TRAP_PAPER = '#EFE6D2'

export type InkBox = { x: number; y: number; width: number; height: number }

export type InkTrapPaint = {
  trap: boolean
  color: string
  paper?: string
  fill?: string
}

export function inkTrapStroke(fontSize: number) {
  return fontSize * INK_TRAP_RATIO
}

export function isBlackPlate(color: string) {
  const match = color.match(/^#([0-9a-fA-F]{6})$/)
  if (!match) return false
  const value = Number.parseInt(match[1], 16)
  return Math.max(value >> 16, (value >> 8) & 255, value & 255) <= 0x2a
}

export function trapsBlackPlate(color: string, fill?: string) {
  if (fill === 'gradient') return true
  return !isBlackPlate(color)
}

/** Glyph box, or the same box grown by the trap stroke. Unchanged when trapping is off. */
export function inkTrapBox(glyph: InkBox, fontSize: number, trap: boolean, color: string): InkBox {
  const grow = inkTrapStroke(fontSize)
  if (!trap || !trapsBlackPlate(color) || !(grow > 0)) return glyph
  const pad = grow / 2
  return { x: glyph.x - pad, y: glyph.y - pad, width: glyph.width + grow, height: glyph.height + grow }
}

export function reserveBlackPlate(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, fontSize: number, ink: InkTrapPaint) {
  if (!ink.trap || !trapsBlackPlate(ink.color, ink.fill)) return
  const lineWidth = ctx.lineWidth
  const strokeStyle = ctx.strokeStyle
  const lineJoin = ctx.lineJoin
  const shadowColor = ctx.shadowColor
  const shadowBlur = ctx.shadowBlur
  ctx.shadowColor = 'rgba(0,0,0,0)'
  ctx.shadowBlur = 0
  ctx.lineJoin = 'round'
  ctx.lineWidth = inkTrapStroke(fontSize)
  ctx.strokeStyle = ink.paper || INK_TRAP_PAPER
  ctx.strokeText(text, x, y)
  ctx.lineWidth = lineWidth
  ctx.strokeStyle = strokeStyle
  ctx.lineJoin = lineJoin
  ctx.shadowColor = shadowColor
  ctx.shadowBlur = shadowBlur
}
