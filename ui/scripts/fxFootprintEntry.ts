// Browser side of the footprint audit (``fx-footprint-audit.mjs`` bundles this file with esbuild and runs it in
// Chromium): paints each catalog effect alone with the real painter and measures where its pixels end.
import { needsFrameSource, paintSceneFx } from '../src/features/sceneFx/paint.ts'
import { FX_CATALOG, parseSceneFx } from '../src/features/sceneFx/types.ts'
import { CUT_RUN, cornerFill, isBoxCut, measureAlpha, type FootprintMeasure } from './fxFootprint.ts'

export type AuditSample = { kind: string; size: number; instants: number[]; seeds: number[] }
/** One effect at one size: the worst frame, and how its paint spreads over all of them. */
export type AuditResult = AuditSample & {
  /** Frames (of the instants and seeds asked) in which the effect painted anything at all: none is a blank effect, which would read as "no cut". */
  painted: number
  screen: boolean; cut: boolean; run: number; fill: number; worst: FootprintMeasure | null; webgl: boolean
}

const WIDTH = 640, HEIGHT = 360, SECONDS = 2

function hasWebgl() {
  const probe = document.createElement('canvas')
  return Boolean(probe.getContext('webgl2') ?? probe.getContext('webgl'))
}

/** A picture for the effects that work on what is under them: two greys in a coarse check, so a grade, a displacement or a
 * grain shows as a change from it. */
function backdrop(width = WIDTH, height = HEIGHT): HTMLCanvasElement {
  const canvas = document.createElement('canvas')
  canvas.width = width; canvas.height = height
  const ctx = canvas.getContext('2d')!
  const cell = Math.max(8, Math.round(height / 12))
  for (let y = 0; y < height; y += cell) for (let x = 0; x < width; x += cell) {
    ctx.fillStyle = ((x + y) / cell) % 2 ? '#707888' : '#5a6272'
    ctx.fillRect(x, y, cell, cell)
  }
  return canvas
}

/** The painted alpha of one cue: its own alpha on a transparent frame or, for an effect that works on the picture under
 * it, how much it changes the backdrop (3x, so a 1 % change counts). */
function paintAlpha(kind: string, size: number, at: number, seed: number) {
  const canvas = document.createElement('canvas')
  canvas.width = WIDTH; canvas.height = HEIGHT
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!
  const cue = parseSceneFx([{ id: `audit-${kind}-${size}-${seed}`, kind, start: 0, end: SECONDS, x: 50, y: 50, size, intensity: 1, seed, sound: false }])[0]
  const sourced = needsFrameSource(kind)
  const source = sourced ? backdrop() : null
  paintSceneFx(ctx, WIDTH, HEIGHT, at * SECONDS, [cue], source)
  const rgba = ctx.getImageData(0, 0, WIDTH, HEIGHT).data
  const alpha = new Uint8Array(WIDTH * HEIGHT)
  if (!source) {
    for (let i = 0; i < alpha.length; i++) alpha[i] = rgba[i * 4 + 3]
    return alpha
  }
  const base = source.getContext('2d')!.getImageData(0, 0, WIDTH, HEIGHT).data
  for (let i = 0; i < alpha.length; i++) {
    const change = Math.max(Math.abs(rgba[i * 4] - base[i * 4]), Math.abs(rgba[i * 4 + 1] - base[i * 4 + 1]), Math.abs(rgba[i * 4 + 2] - base[i * 4 + 2]))
    alpha[i] = Math.min(255, change * 3)
  }
  return alpha
}

/** A contact sheet of every effect at one instant on a mid-grey, each tile with the footprint (red) and the painted box (cyan). */
async function sheet(size: number, at: number, seed: number, only?: string[]): Promise<string> {
  const kinds = only ?? FX_CATALOG.map(item => item.id)
  const cols = 6, tileWidth = 320, tileHeight = 180, rows = Math.ceil(kinds.length / cols)
  const out = document.createElement('canvas')
  out.width = cols * tileWidth; out.height = rows * tileHeight
  const g = out.getContext('2d')!
  g.fillStyle = '#5a6070'; g.fillRect(0, 0, out.width, out.height)
  for (const [index, kind] of kinds.entries()) {
    const alpha = paintAlpha(kind, size, at, seed)
    const canvas = document.createElement('canvas')
    canvas.width = WIDTH; canvas.height = HEIGHT
    const ctx = canvas.getContext('2d')!
    const cue = parseSceneFx([{ id: `audit-${kind}-${size}-${seed}`, kind, start: 0, end: SECONDS, x: 50, y: 50, size, intensity: 1, seed, sound: false }])[0]
    paintSceneFx(ctx, WIDTH, HEIGHT, at * SECONDS, [cue], needsFrameSource(kind) ? backdrop() : null)
    const ox = (index % cols) * tileWidth, oy = Math.floor(index / cols) * tileHeight, k = tileWidth / WIDTH
    g.drawImage(canvas, ox, oy, tileWidth, tileHeight)
    const side = Math.min(WIDTH, HEIGHT) * size / 100 * k
    g.strokeStyle = 'rgba(255,70,70,.8)'; g.strokeRect(ox + tileWidth / 2 - side / 2, oy + tileHeight / 2 - side / 2, side, side)
    const box = measureAlpha(alpha, WIDTH, HEIGHT, { cx: WIDTH / 2, cy: HEIGHT / 2, side: 1 }).box
    if (box) { g.strokeStyle = 'rgba(70,230,255,.9)'; g.strokeRect(ox + box.left * k, oy + box.top * k, (box.right - box.left) * k, (box.bottom - box.top) * k) }
    g.fillStyle = '#fff'; g.font = '11px monospace'; g.fillText(kind, ox + 4, oy + 12)
  }
  return out.toDataURL('image/png')
}

/** One frame of a shot's screen effects as a Series render paints them, over a backdrop: the picture (PNG data URL),
 * the share of the frame the effects change and the box they change. */
function frame(cues: unknown, seconds: number, width: number, height: number) {
  const canvas = document.createElement('canvas')
  canvas.width = width; canvas.height = height
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!
  const source = backdrop(width, height)
  ctx.drawImage(source, 0, 0)
  paintSceneFx(ctx, width, height, seconds, parseSceneFx(cues), source)
  const rgba = ctx.getImageData(0, 0, width, height).data
  const base = source.getContext('2d')!.getImageData(0, 0, width, height).data
  const change = new Uint8Array(width * height)
  for (let i = 0; i < change.length; i++) {
    const delta = Math.max(Math.abs(rgba[i * 4] - base[i * 4]), Math.abs(rgba[i * 4 + 1] - base[i * 4 + 1]), Math.abs(rgba[i * 4 + 2] - base[i * 4 + 2]))
    change[i] = Math.min(255, delta * 3)
  }
  const measure = measureAlpha(change, width, height, { cx: width / 2, cy: height / 2, side: Math.min(width, height) })
  return { png: canvas.toDataURL('image/png'), coverage: measure.coverage, box: measure.box }
}

function run(sample: AuditSample): AuditResult {
  const { kind, size } = sample
  const webgl = hasWebgl()
  const empty = { ...sample, painted: 0, screen: false, cut: false, run: 0, fill: 0, worst: null, webgl }
  const footprint = { cx: WIDTH / 2, cy: HEIGHT / 2, side: Math.min(WIDTH, HEIGHT) * size / 100 }
  const mass = new Float32Array(WIDTH * HEIGHT)
  let worst: FootprintMeasure | null = null, screens = 0, painted = 0, run = 0
  for (const seed of sample.seeds) for (const at of sample.instants) {
    const alpha = paintAlpha(kind, size, at, seed)
    const measure = measureAlpha(alpha, WIDTH, HEIGHT, footprint)
    if (!measure.box) continue
    painted++
    if (measure.screen) { screens++; continue }
    for (let i = 0; i < alpha.length; i++) mass[i] += alpha[i]
    run = Math.max(run, measure.cut)
    if (!worst || measure.cut > worst.cut) worst = measure
  }
  // A frame that spans the frame (a lightning flash) has no footprint to end against: the others are measured.
  if (!worst) return { ...empty, painted, screen: screens > 0 }
  const fill = cornerFill(mass, WIDTH, HEIGHT, footprint)
  return { ...sample, painted, screen: false, cut: isBoxCut(worst, fill) || run >= CUT_RUN, run, fill, worst, webgl }
}

;(window as unknown as { fxAudit: unknown }).fxAudit = { kinds: FX_CATALOG.map(item => item.id), run, sheet, frame }
