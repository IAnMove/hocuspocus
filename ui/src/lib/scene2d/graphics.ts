// Parameterized drawings for a text cue's graphic field. scene2d/paint.ts
// reaches them through paintKineticTexts. No cue graphic means these never run.
import catalog from '../../../../app/shared/scene_graphics.json' with { type: 'json' }
import type { KineticText, TextGraphic } from '../kineticText/types'
import { paintTilingDesktop } from './tilingDesktop'

type GraphicParam = {
  key: string
  type: 'number' | 'color' | 'enum'
  default: number | string
  min?: number
  max?: number
  integer?: boolean
  values?: string[]
}
type GraphicEntry = {
  id: string
  beats: Record<string, number>
  params: GraphicParam[]
}
type Resolved = Record<string, number | string>
type Painter = (ctx: CanvasRenderingContext2D, cue: KineticText, width: number, height: number, seconds: number, params: Resolved, beats: Record<string, number>, pulse: number) => void

const entries = catalog.entries as unknown as GraphicEntry[]
const byId = new Map(entries.map(entry => [entry.id, entry]))
const PERSON: ReadonlyArray<readonly [number, number]> = [
  [0, -0.42], [0.1, -0.36], [-0.1, -0.36], [0.14, -0.44], [-0.14, -0.44], [0, -0.28],
  [0.18, -0.08], [-0.18, -0.08], [0.16, 0.08], [-0.16, 0.08], [0.08, 0.2], [-0.08, 0.2],
  [0.1, 0.4], [-0.1, 0.4], [0.16, 0.48], [-0.16, 0.48],
]
const HEART: ReadonlyArray<readonly [number, number]> = [
  [0, 0.12], [0.12, -0.02], [-0.12, -0.02], [0.22, -0.16], [-0.22, -0.16], [0.28, -0.28],
  [-0.28, -0.28], [0.16, -0.36], [-0.16, -0.36], [0, -0.22], [0.08, 0.28], [-0.08, 0.28], [0, 0.4],
]
const STAR: ReadonlyArray<readonly [number, number]> = [
  [0, -0.46], [0.12, -0.14], [0.46, -0.14], [0.18, 0.06], [0.28, 0.42], [0, 0.18],
  [-0.28, 0.42], [-0.18, 0.06], [-0.46, -0.14], [-0.12, -0.14],
]

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))

function hashId(id: string) {
  let hash = 2166136261
  for (let index = 0; index < id.length; index += 1) hash = Math.imul(hash ^ id.charCodeAt(index), 16777619)
  return (hash >>> 0) || 1
}

function unit(seed: number, index: number) {
  let value = Math.imul(seed ^ (index + 1), 0x45d9f3b)
  value = Math.imul(value ^ (value >>> 16), 0x45d9f3b)
  return ((value ^ (value >>> 16)) >>> 0) / 4294967296
}

function beatOf(beats: Record<string, number>, key: string, fallback: number) {
  const value = beats[key]
  return typeof value === 'number' && value > 0 ? value : fallback
}

function cueBeat(cue: KineticText, seconds: number, span: number) {
  const duration = Math.max(0.05, cue.end - cue.start)
  return clamp((seconds - cue.start) / duration, 0, 1) * span
}

function specValue(spec: GraphicParam, raw: unknown): number | string {
  if (spec.type === 'enum') {
    const values = spec.values ?? []
    return typeof raw === 'string' && values.includes(raw) ? raw : String(spec.default)
  }
  if (spec.type === 'color') {
    return typeof raw === 'string' && /^#[0-9a-fA-F]{6}$/.test(raw) ? raw : String(spec.default)
  }
  const fallback = typeof spec.default === 'number' ? spec.default : 0
  const value = typeof raw === 'number' && Number.isFinite(raw) ? raw : fallback
  const bounded = clamp(value, spec.min ?? value, spec.max ?? value)
  return spec.integer ? Math.round(bounded) : bounded
}

function resolved(entry: GraphicEntry, raw: TextGraphic['params']): Resolved {
  const params: Resolved = {}
  for (const spec of entry.params) params[spec.key] = specValue(spec, raw?.[spec.key])
  return params
}

export function parseGraphicCue(value: unknown): TextGraphic | undefined {
  if (!value || typeof value !== 'object') return undefined
  const raw = value as { id?: unknown; params?: unknown }
  if (typeof raw.id !== 'string' || !byId.has(raw.id)) return undefined
  const entry = byId.get(raw.id)
  if (!entry || !raw.params || typeof raw.params !== 'object' || Array.isArray(raw.params)) return { id: raw.id }
  const source = raw.params as Record<string, unknown>
  const params: Resolved = {}
  for (const spec of entry.params) {
    if (!Object.prototype.hasOwnProperty.call(source, spec.key)) continue
    params[spec.key] = specValue(spec, source[spec.key])
  }
  return Object.keys(params).length ? { id: raw.id, params } : { id: raw.id }
}

function place(ctx: CanvasRenderingContext2D, cue: KineticText, width: number, height: number, pulse: number) {
  const size = Math.max(4, Math.min(width, height) * (cue.size / 100) * pulse)
  ctx.translate(width * cue.x / 100, height * cue.y / 100)
  return size
}

function chartHeight(series: string, index: number, count: number, amplitude: number, seed: number) {
  const t = count <= 1 ? 0 : index / (count - 1)
  if (series === 'exponential') {
    const peak = Math.exp(amplitude) - 1
    return peak > 0 ? (Math.exp(t * amplitude) - 1) / peak : t
  }
  if (series === 'candles') return 0.25 + unit(seed, index) * 0.6
  return clamp(0.55 + Math.sin((t * 2 + amplitude) * Math.PI) * 0.35, 0.08, 0.95)
}

function paintChart(ctx: CanvasRenderingContext2D, cue: KineticText, width: number, height: number, seconds: number, params: Resolved, beats: Record<string, number>, pulse: number) {
  const count = Number(params.points)
  const shown = Math.max(2, Math.round(count * clamp(cueBeat(cue, seconds, beatOf(beats, 'span', 8)) / beatOf(beats, 'reveal', 8), 0, 1)))
  ctx.save()
  const size = place(ctx, cue, width, height, pulse)
  ctx.fillStyle = String(params.color)
  const slot = size / count
  const barWidth = params.series === 'candles' ? slot * 0.55 : slot * 0.72
  for (let index = 0; index < shown; index += 1) {
    const bar = Math.max(1, chartHeight(String(params.series), index, count, Number(params.amplitude), hashId(cue.id)) * size)
    ctx.fillRect(-size / 2 + index * slot, size / 2 - bar, Math.max(1, barWidth), bar)
  }
  ctx.restore()
}

function paintOdometer(ctx: CanvasRenderingContext2D, cue: KineticText, width: number, height: number, seconds: number, params: Resolved, beats: Record<string, number>, pulse: number) {
  const t = clamp(cueBeat(cue, seconds, beatOf(beats, 'span', 4)) / beatOf(beats, 'roll', 4), 0, 1)
  const value = Number(params.from) + (Number(params.to) - Number(params.from)) * t * t * (3 - 2 * t)
  const digits = Number(params.digits)
  const text = Math.abs(Math.round(value)).toString().padStart(digits, '0').slice(-digits)
  ctx.save()
  const size = place(ctx, cue, width, height, pulse)
  const cell = size / digits
  ctx.fillStyle = String(params.color)
  ctx.font = `700 ${Math.max(8, cell * 0.8)}px sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  for (let index = 0; index < text.length; index += 1) {
    const digit = Number(text[index])
    const x = -size / 2 + index * cell
    ctx.globalAlpha = 1
    ctx.fillRect(x, size * 0.08, cell * 0.78, Math.max(2, (digit + 1) / 10 * size * 0.42))
    ctx.fillText(text[index], x + cell * 0.39, -size * 0.12)
  }
  ctx.restore()
}

function paintOrbit(ctx: CanvasRenderingContext2D, cue: KineticText, width: number, height: number, seconds: number, params: Resolved, beats: Record<string, number>, pulse: number) {
  const count = Number(params.count)
  const turns = cueBeat(cue, seconds, beatOf(beats, 'span', 8)) / beatOf(beats, 'period', 4) * Number(params.speed)
  ctx.save()
  const size = place(ctx, cue, width, height, pulse)
  const radius = size * Number(params.radius)
  ctx.fillStyle = String(params.color)
  for (let index = 0; index < count; index += 1) {
    const angle = turns * Math.PI * 2 + index * Math.PI * 2 / count
    ctx.beginPath()
    ctx.arc(Math.cos(angle) * radius, Math.sin(angle) * radius, Math.max(1.5, size * 0.07), 0, Math.PI * 2)
    ctx.fill()
  }
  ctx.restore()
}

function shapePoints(shape: string) {
  if (shape === 'heart') return HEART
  if (shape === 'star') return STAR
  return PERSON
}

function paintSilhouette(ctx: CanvasRenderingContext2D, cue: KineticText, width: number, height: number, seconds: number, params: Resolved, beats: Record<string, number>, pulse: number) {
  const form = clamp(cueBeat(cue, seconds, beatOf(beats, 'span', 8)) / beatOf(beats, 'form', 8), 0, 1) * Number(params.gather)
  const targets = shapePoints(String(params.shape))
  const count = Number(params.count)
  const seed = hashId(cue.id)
  ctx.save()
  const size = place(ctx, cue, width, height, pulse)
  ctx.fillStyle = String(params.color)
  for (let index = 0; index < count; index += 1) {
    const target = targets[index % targets.length]
    const sx = (unit(seed, index) - 0.5) * size
    const sy = (unit(seed, index + 19) - 0.5) * size
    ctx.fillRect(sx + (target[0] * size - sx) * form - 1.2, sy + (target[1] * size - sy) * form - 1.2, 2.4, 2.4)
  }
  ctx.restore()
}

function paintShatter(ctx: CanvasRenderingContext2D, cue: KineticText, width: number, height: number, seconds: number, params: Resolved, beats: Record<string, number>, pulse: number) {
  const pieces = Number(params.pieces)
  const cols = Math.max(1, Math.ceil(Math.sqrt(pieces)))
  const rows = Math.max(1, Math.ceil(pieces / cols))
  const burst = clamp(cueBeat(cue, seconds, beatOf(beats, 'span', 4)) / beatOf(beats, 'burst', 4), 0, 1)
  const seed = hashId(cue.id)
  ctx.save()
  const size = place(ctx, cue, width, height, pulse)
  ctx.fillStyle = String(params.color)
  let drawn = 0
  for (let row = 0; row < rows && drawn < pieces; row += 1) {
    for (let col = 0; col < cols && drawn < pieces; col += 1) {
      const ox = (unit(seed, drawn) - 0.5) * size * Number(params.spread) * burst
      const oy = (unit(seed, drawn + 5) - 0.5) * size * Number(params.spread) * burst
      const cellW = size / cols
      const cellH = size / rows
      ctx.save()
      ctx.translate(-size / 2 + (col + 0.5) * cellW + ox, -size / 2 + (row + 0.5) * cellH + oy)
      ctx.rotate((unit(seed, drawn + 11) - 0.5) * Number(params.spin) * burst)
      ctx.fillRect(-cellW * 0.32, -cellH * 0.32, cellW * 0.64, cellH * 0.64)
      ctx.restore()
      drawn += 1
    }
  }
  ctx.restore()
}

function paintCountdown(ctx: CanvasRenderingContext2D, cue: KineticText, width: number, height: number, seconds: number, params: Resolved, beats: Record<string, number>, pulse: number) {
  const left = Math.max(0, Number(params.from) - Math.floor(cueBeat(cue, seconds, beatOf(beats, 'span', 8)) / beatOf(beats, 'step', 1)))
  ctx.save()
  const size = place(ctx, cue, width, height, pulse)
  ctx.fillStyle = String(params.color)
  if (Number(params.rings) > 0) {
    ctx.beginPath()
    ctx.arc(0, 0, size * 0.46, 0, Math.PI * 2)
    ctx.fill()
  } else ctx.fillRect(-size * 0.22, -size * 0.22, size * 0.44, size * 0.44)
  paintTicks(ctx, size, Number(params.ticks), left)
  ctx.fillStyle = '#10141c'
  ctx.font = `700 ${Math.max(8, size * 0.42)}px sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(String(left), 0, 1)
  ctx.restore()
}

function paintTicks(ctx: CanvasRenderingContext2D, size: number, ticks: number, left: number) {
  const lit = ticks - (left % ticks)
  ctx.save()
  ctx.fillStyle = '#10141c'
  for (let index = 0; index < ticks; index += 1) {
    if (index >= lit) continue
    const angle = -Math.PI / 2 + index / ticks * Math.PI * 2
    ctx.fillRect(Math.cos(angle) * size * 0.3 - 1.2, Math.sin(angle) * size * 0.3 - 1.2, 2.4, 2.4)
  }
  ctx.restore()
}

function paintTiling(ctx: CanvasRenderingContext2D, cue: KineticText, width: number, height: number, seconds: number, params: Resolved, beats: Record<string, number>) {
  paintTilingDesktop(ctx, width, height, seconds, cueBeat(cue, seconds, beatOf(beats, 'span', 8)), beats, params)
}

const PAINTERS: Record<string, Painter> = {
  chart: paintChart,
  odometer: paintOdometer,
  orbit: paintOrbit,
  silhouette: paintSilhouette,
  shatter: paintShatter,
  countdown: paintCountdown,
  tiling: paintTiling,
}

export function paintSceneGraphic(ctx: CanvasRenderingContext2D, width: number, height: number, seconds: number, cue: KineticText, pulse = 1) {
  const graphic = cue.graphic
  if (!graphic) return
  const entry = byId.get(graphic.id)
  const paint = entry ? PAINTERS[entry.id] : undefined
  if (!entry || !paint) return
  paint(ctx, cue, width, height, seconds, resolved(entry, graphic.params), entry.beats, pulse)
}
