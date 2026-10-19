// Browser side of the presence-effect contact sheets (``fx-presence-sheets.mjs`` bundles this file with esbuild and runs
// it in Chromium). Paints a Series shot's screen effects with the real painter over a scene-like backdrop (a night
// sky into warm ground, a figure in the middle) at the start, middle and end of the shot, and lays the frames out as one
// PNG per call. It is also the timing harness: ``time`` paints the frames of a shot and reports ms per frame.
import { paintSceneFx } from '../src/features/sceneFx/paint.ts'
import { setPresenceEnabled } from '../src/features/sceneFx/presence/index.ts'
import { parseSceneFx } from '../src/features/sceneFx/types.ts'

export type SheetRow = { label?: string; cues: Array<Record<string, unknown>> }
export type SheetSpec = { rows: SheetRow[]; instants: number[]; duration: number; width: number; height: number; tileWidth: number; backdrop?: 'scene' | 'light' }

/** The picture under the effects: a dusk gradient, a floor and a standing figure (the subject an aura or a shield wraps). */
export function backdrop(width: number, height: number, kind: 'scene' | 'light' = 'scene'): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width; canvas.height = height
  const g = canvas.getContext('2d')!
  const sky = g.createLinearGradient(0, 0, 0, height)
  if (kind === 'light') { sky.addColorStop(0, '#b9c8d8'); sky.addColorStop(.62, '#d9d2c2'); sky.addColorStop(1, '#8c8474') }
  else { sky.addColorStop(0, '#0d1226'); sky.addColorStop(.6, '#2c3350'); sky.addColorStop(1, '#4a4538') }
  g.fillStyle = sky; g.fillRect(0, 0, width, height)
  g.fillStyle = kind === 'light' ? '#6f6a5c' : '#2a2822'; g.fillRect(0, height * .72, width, height * .28)
  g.fillStyle = kind === 'light' ? '#3a3a44' : '#05060c'
  const cx = width / 2, base = height * .86, unit = height / 720
  g.beginPath(); g.ellipse(cx, base - 262 * unit, 34 * unit, 40 * unit, 0, 0, Math.PI * 2); g.fill()
  g.beginPath(); g.moveTo(cx - 62 * unit, base - 214 * unit); g.lineTo(cx + 62 * unit, base - 214 * unit)
  g.lineTo(cx + 46 * unit, base - 40 * unit); g.lineTo(cx - 46 * unit, base - 40 * unit); g.closePath(); g.fill()
  g.fillRect(cx - 44 * unit, base - 44 * unit, 36 * unit, 44 * unit); g.fillRect(cx + 8 * unit, base - 44 * unit, 36 * unit, 44 * unit)
  return canvas
}

function frame(cues: unknown, seconds: number, width: number, height: number, kind: 'scene' | 'light'): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width; canvas.height = height
  const ctx = canvas.getContext('2d')!
  const source = backdrop(width, height, kind)
  ctx.drawImage(source, 0, 0)
  paintSceneFx(ctx, width, height, seconds, parseSceneFx(cues), source)
  return canvas
}

function sheet(spec: SheetSpec): string {
  const { rows, instants, duration, width, height, tileWidth } = spec
  const tileHeight = Math.round(tileWidth * height / width), gutter = 4, label = 120
  const out = document.createElement('canvas')
  out.width = label + instants.length * (tileWidth + gutter); out.height = rows.length * (tileHeight + gutter)
  const g = out.getContext('2d')!
  g.fillStyle = '#000'; g.fillRect(0, 0, out.width, out.height)
  rows.forEach((row, r) => {
    g.fillStyle = '#fff'; g.font = '13px monospace'
    g.fillText(row.label ?? String(row.cues[0]?.kind ?? ''), 6, r * (tileHeight + gutter) + 18)
    instants.forEach((at, c) => {
      const tile = frame(row.cues, at * duration, width, height, spec.backdrop ?? 'scene')
      g.drawImage(tile, label + c * (tileWidth + gutter), r * (tileHeight + gutter), tileWidth, tileHeight)
    })
  })
  return out.toDataURL('image/png')
}

/** One full-size frame as a PNG data URL. */
function still(cues: unknown, seconds: number, width: number, height: number, kind: 'scene' | 'light' = 'scene'): string {
  return frame(cues, seconds, width, height, kind).toDataURL('image/png')
}

/** The PNG of one frame and a hash of its pixels (a determinism check across calls and pages). */
function pixels(cues: unknown, seconds: number, width: number, height: number) {
  const canvas = frame(cues, seconds, width, height, 'scene')
  const data = canvas.getContext('2d')!.getImageData(0, 0, width, height).data
  let hash = 2166136261, lit = 0
  for (let i = 0; i < data.length; i += 4) {
    hash = Math.imul(hash ^ data[i] ^ (data[i + 1] << 8) ^ (data[i + 2] << 16), 16777619) >>> 0
    if (data[i] + data[i + 1] + data[i + 2] > 0) lit++
  }
  return { hash, lit }
}

/** Milliseconds per frame of a shot's cues over `frames` frames, the first (which builds the GPU state) apart. */
function time(cues: unknown, width: number, height: number, frames: number, duration: number) {
  const parsed = parseSceneFx(cues)
  const canvas = document.createElement('canvas')
  canvas.width = width; canvas.height = height
  const ctx = canvas.getContext('2d')!
  const paint = (index: number) => {
    ctx.clearRect(0, 0, width, height)
    paintSceneFx(ctx, width, height, index / frames * duration, parsed)
    ctx.getImageData(0, 0, 1, 1)
  }
  const first = performance.now(); paint(0); const warm = performance.now() - first
  const start = performance.now()
  for (let i = 1; i <= frames; i++) paint(i)
  return { warm, perFrame: (performance.now() - start) / frames }
}

function hasWebgl() {
  const probe = document.createElement('canvas')
  return Boolean(probe.getContext('webgl2') ?? probe.getContext('webgl'))
}

;(window as unknown as { fxSheet: unknown }).fxSheet = { sheet, still, pixels, time, hasWebgl, presence: setPresenceEnabled }
