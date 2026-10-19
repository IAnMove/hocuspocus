import type { SceneFx } from './types'

/** The scanner covers the whole frame, like the other grades: hairlines across its full width and height and one
 * bright line that sweeps down it. `size` is the height of the pattern in % of the frame's shorter side (32 hairlines
 * to it, as before) and `intensity` is not used; x, y and rotation do not move it. It is painted outside the cue's
 * x/y/size transform, so no box of lines shows inside the picture. */
export const SCANLINE_KIND = 'scanline'
const HAIRLINES = 32
/** Pattern speed of the sweep, in patterns per second. */
const SWEEP = .35

export function paintScanline(ctx: CanvasRenderingContext2D, cue: SceneFx, time: number, width: number, height: number) {
  const pattern = Math.min(width, height) * cue.size / 100
  const pitch = Math.max(2, pattern / HAIRLINES)
  ctx.save()
  ctx.strokeStyle = cue.color; ctx.lineCap = 'butt'
  ctx.lineWidth = Math.max(1, pattern * .002); ctx.globalAlpha = .2
  ctx.beginPath()
  for (let y = pitch / 2; y < height; y += pitch) { ctx.moveTo(0, y); ctx.lineTo(width, y) }
  ctx.stroke()
  const sweep = (time * SWEEP * pattern) % height
  ctx.lineWidth = Math.max(1, pattern * .008); ctx.globalAlpha = .8
  ctx.beginPath(); ctx.moveTo(0, sweep); ctx.lineTo(width, sweep); ctx.stroke()
  ctx.restore()
}
