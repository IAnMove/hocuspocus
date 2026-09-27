import { withAlpha } from './color'
import type { SceneFx } from './types'

export type FxPainter = (ctx: CanvasRenderingContext2D, cue: SceneFx, time: number, progress: number) => void
export const TAU = Math.PI * 2
export function ring(ctx: CanvasRenderingContext2D, radius: number, width = .004) {
  ctx.lineWidth = width; ctx.beginPath(); ctx.arc(0, 0, Math.max(.001, radius), 0, TAU); ctx.stroke()
}
export function glow(ctx: CanvasRenderingContext2D, color: string, radius: number, opacity = 1) {
  const gradient = ctx.createRadialGradient(0, 0, 0, 0, 0, radius)
  gradient.addColorStop(0, '#ffffff'); gradient.addColorStop(.12, color); gradient.addColorStop(1, withAlpha(color, '00'))
  ctx.save(); ctx.globalAlpha *= opacity; ctx.fillStyle = gradient
  ctx.fillRect(-radius, -radius, radius * 2, radius * 2); ctx.restore()
}
export function strokeEnergy(ctx: CanvasRenderingContext2D, color: string, width: number) {
  ctx.strokeStyle = color; ctx.lineWidth = width * 3; ctx.globalAlpha *= .2; ctx.stroke()
  ctx.globalAlpha *= 5; ctx.lineWidth = width; ctx.stroke()
  ctx.strokeStyle = '#efffff'; ctx.lineWidth = width * .27; ctx.stroke()
}
export function star(ctx: CanvasRenderingContext2D, x: number, y: number, size: number) {
  ctx.beginPath(); ctx.moveTo(x, y - size); ctx.lineTo(x + size * .22, y - size * .22)
  ctx.lineTo(x + size, y); ctx.lineTo(x + size * .22, y + size * .22); ctx.lineTo(x, y + size)
  ctx.lineTo(x - size * .22, y + size * .22); ctx.lineTo(x - size, y); ctx.lineTo(x - size * .22, y - size * .22)
  ctx.closePath(); ctx.fill()
}
