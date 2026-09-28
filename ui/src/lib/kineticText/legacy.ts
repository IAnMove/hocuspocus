// The Video 2D text painter as it shipped before optional v2 fields.
// Cues that do not set those fields must keep calling this path.
import { reserveBlackPlate, type InkTrapPaint } from '../scene2d/inkTrap'
import type { KineticText } from './types'

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))

export function legacyTextState(cue: KineticText, seconds: number) {
  const elapsed = seconds - cue.start
  const enter = clamp(elapsed / Math.min(.65, (cue.end - cue.start) / 3), 0, 1)
  const exit = clamp((cue.end - seconds) / Math.min(.3, (cue.end - cue.start) / 3), 0, 1)
  const impact = .65 * (1 - enter) ** 2 * Math.cos(enter * Math.PI * 3)
  return {
    elapsed, opacity: Math.min(1, enter * 5) * exit,
    scale: cue.preset === 'impact' ? 1 + impact : 1,
    dy: cue.preset === 'rise' ? (1 - enter) ** 3 * .22 : 0,
    letters: cue.preset === 'typewriter' ? Math.ceil(Array.from(cue.text).length * clamp(elapsed / Math.min(1.7, (cue.end - cue.start) * .65), 0, 1)) : Array.from(cue.text).length,
  }
}

function paintTextLine(ctx: CanvasRenderingContext2D, text: string, y: number, cue: KineticText, time: number, size: number, ink: InkTrapPaint) {
  if (cue.preset !== 'wave') {
    ctx.strokeText(text, 0, y)
    reserveBlackPlate(ctx, text, 0, y, size, ink)
    ctx.fillText(text, 0, y)
    return
  }
  let x = -ctx.measureText(text).width / 2
  ctx.textAlign = 'left'
  Array.from(text).forEach((letter, index) => {
    const dy = Math.sin(time * 5.6 - index * .42) * size * .14
    ctx.strokeText(letter, x, y + dy)
    reserveBlackPlate(ctx, letter, x, y + dy, size, ink)
    ctx.fillText(letter, x, y + dy)
    x += ctx.measureText(letter).width
  })
  ctx.textAlign = 'center'
}

export function paintLegacyCue(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, cue: KineticText, pulse = 1, ink: InkTrapPaint = { trap: false, color: cue.color }) {
  const state = legacyTextState(cue, seconds)
  ctx.save()
  let size = height * cue.size / 100
  const font = (pixels: number) => cue.font === 'mono' ? `700 ${pixels}px ui-monospace, monospace` : `900 ${pixels}px system-ui, sans-serif`
  ctx.font = font(size)
  const lines = cue.text.split('\n')
  const textWidth = Math.max(1, ...lines.map(line => ctx.measureText(line).width))
  size *= Math.min(1, width * .86 / textWidth)
  ctx.font = font(size)
  ctx.translate(width * cue.x / 100, height * (cue.y / 100 + state.dy))
  ctx.rotate(cue.rotation * Math.PI / 180)
  ctx.scale(state.scale * pulse, state.scale * pulse)
  ctx.globalAlpha = state.opacity
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'; ctx.lineJoin = 'round'
  ctx.strokeStyle = '#07101e'; ctx.lineWidth = Math.max(3, size * .085)
  ctx.fillStyle = cue.color; ctx.shadowColor = '#020711'; ctx.shadowBlur = size * .12
  ctx.shadowOffsetY = size * .065
  let remaining = state.letters
  lines.forEach((line, index) => {
    const letters = Array.from(line)
    paintTextLine(ctx, letters.slice(0, Math.max(0, remaining)).join(''), (index - (lines.length - 1) / 2) * size * 1.12, cue, state.elapsed, size, { ...ink, color: cue.color })
    remaining -= letters.length + 1
  })
  ctx.restore()
}
