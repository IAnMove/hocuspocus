import { fxRandom, type SceneFx } from './types'

/** Anime impact frames fill the whole picture, so they are painted outside the cue's
 * x/y/size transform. x/y place the vanishing point of the focus lines; size sets the clear
 * circle around it; intensity sets how many lines there are and how opaque the flash is. */
export const FRAME_FX_KINDS = ['impact_flash', 'impact_invert'] as const
const INK = '#0b0b14'
const TAU = Math.PI * 2

export function isFrameFx(kind: string): boolean {
  return (FRAME_FX_KINDS as readonly string[]).includes(kind)
}

/** Three beats of a 2-4 frame cue: the solid frame, the frame with lines, the release.
 * Long cues keep the first two beats short and spend the rest releasing. */
export function impactBeat(cue: Pick<SceneFx, 'start' | 'end'>, time: number): { beat: 0 | 1 | 2; fade: number } {
  const span = Math.max(1e-6, cue.end - cue.start)
  const solid = Math.min(span * .22, .09), lines = Math.min(span * .55, .2)
  if (time < solid) return { beat: 0, fade: 1 }
  if (time < lines) return { beat: 1, fade: 1 }
  return { beat: 2, fade: Math.max(0, 1 - (time - lines) / Math.max(1e-6, span - lines)) ** 2 }
}

/** Manga focus lines: wedges that widen toward the frame edges, around a clear centre. */
function focusLines(ctx: CanvasRenderingContext2D, cue: SceneFx, width: number, height: number, color: string, alpha: number, beat: number) {
  const cx = width * cue.x / 100, cy = height * cue.y / 100
  const inner = Math.min(width, height) * cue.size / 260
  const outer = Math.hypot(width, height)
  const count = Math.max(8, Math.round(56 * cue.intensity))
  const seed = cue.seed + beat * 97
  ctx.globalAlpha = alpha; ctx.fillStyle = color
  for (let i = 0; i < count; i++) {
    const angle = (i + fxRandom(seed, i) * .8) / count * TAU
    const spread = .004 + fxRandom(seed, i + 400) * .018
    const start = inner * (1 + fxRandom(seed, i + 800) * .7)
    ctx.beginPath()
    ctx.moveTo(cx + Math.cos(angle) * start, cy + Math.sin(angle) * start)
    ctx.lineTo(cx + Math.cos(angle - spread) * outer, cy + Math.sin(angle - spread) * outer)
    ctx.lineTo(cx + Math.cos(angle + spread) * outer, cy + Math.sin(angle + spread) * outer)
    ctx.closePath(); ctx.fill()
  }
}

function fill(ctx: CanvasRenderingContext2D, color: string, alpha: number, width: number, height: number) {
  ctx.globalAlpha = alpha; ctx.fillStyle = color; ctx.fillRect(0, 0, width, height)
}

/** White (or `color`) frame, then the same frame crossed by ink lines, then a fading release. */
function flash(ctx: CanvasRenderingContext2D, cue: SceneFx, time: number, width: number, height: number) {
  const { beat, fade } = impactBeat(cue, time)
  const strength = Math.min(1, cue.intensity)
  if (beat === 0) { fill(ctx, cue.color, strength, width, height); return }
  fill(ctx, cue.color, beat === 1 ? .94 * strength : .55 * fade * strength, width, height)
  focusLines(ctx, cue, width, height, INK, beat === 1 ? 1 : fade, beat)
}

/** The negative of the frame (difference with white), then the negative crossed by lines in
 * `color`, then those lines fading over the normal picture. Needs the frame under it: exports
 * paint over it, and the editor overlay copies the stage first. */
function invert(ctx: CanvasRenderingContext2D, cue: SceneFx, time: number, width: number, height: number) {
  const { beat, fade } = impactBeat(cue, time)
  if (beat < 2) {
    ctx.globalCompositeOperation = 'difference'
    fill(ctx, '#ffffff', 1, width, height)
    ctx.globalCompositeOperation = 'source-over'
    if (beat === 1) focusLines(ctx, cue, width, height, cue.color, 1, beat)
    return
  }
  fill(ctx, cue.color, .35 * fade * Math.min(1, cue.intensity), width, height)
  focusLines(ctx, cue, width, height, cue.color, fade, beat)
}

export function paintFrameFx(ctx: CanvasRenderingContext2D, cue: SceneFx, time: number, width: number, height: number) {
  ctx.save()
  if (cue.kind === 'impact_invert') invert(ctx, cue, time, width, height)
  else flash(ctx, cue, time, width, height)
  ctx.restore()
}
