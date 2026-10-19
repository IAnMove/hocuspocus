import assert from 'node:assert/strict'
import test from 'node:test'
import { coversFrame, paintSceneFx } from '../src/features/sceneFx/paint.ts'
import { parseSceneFx } from '../src/features/sceneFx/types.ts'
import { CORNER_LIMIT, CUT_RUN, cornerFill, isBoxCut, measureAlpha } from '../scripts/fxFootprint.ts'

const W = 320, H = 180
const FOOTPRINT = { cx: W / 2, cy: H / 2, side: 90 }

/** An alpha buffer painted by `alpha(x, y)` (0-255). */
function paint(alpha: (x: number, y: number) => number) {
  const data = new Uint8Array(W * H)
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) data[y * W + x] = Math.round(Math.max(0, Math.min(255, alpha(x, y))))
  return data
}

const smooth = (from: number, to: number, value: number) => {
  const t = Math.max(0, Math.min(1, (value - from) / (to - from)))
  return t * t * (3 - 2 * t)
}

test('a glow that decays to nothing before its box is not a cut', () => {
  const glow = paint((x, y) => 230 * (1 - smooth(.15, 1, Math.hypot(x - W / 2, y - H / 2) / 60)))
  const measure = measureAlpha(glow, W, H, FOOTPRINT)
  assert.equal(measure.screen, false)
  assert.ok(measure.cut < CUT_RUN, `cut ${measure.cut}`)
  assert.equal(isBoxCut(measure, cornerFill(glow, W, H, FOOTPRINT)), false)
})

test('paint that stops flat at a rectangle is a cut, whichever side it is on', () => {
  for (const [name, inside] of [
    ['right', (x: number, y: number) => x < 200 && Math.abs(y - 90) < 40],
    ['bottom', (x: number, y: number) => y < 140 && Math.abs(x - 160) < 40],
  ] as const) {
    const flat = paint((x, y) => inside(x, y) ? 200 : 0)
    const measure = measureAlpha(flat, W, H, FOOTPRINT)
    assert.ok(measure.cut >= CUT_RUN, `${name}: cut ${measure.cut}`)
    assert.equal(isBoxCut(measure), true, name)
  }
})

test('a thin stroke along the side of its own box is a line, not a cut', () => {
  const stroke = paint((x, y) => Math.abs(x - 100) < 1.5 && y > 40 && y < 140 ? 255 : 0)
  assert.equal(isBoxCut(measureAlpha(stroke, W, H, FOOTPRINT)), false)
})

test('a beam with a soft end and a rounded tip is not a cut', () => {
  const beam = paint((x, y) => 255 * Math.exp(-(((y - 90) / 10) ** 2)) * (1 - smooth(150, 260, x)) * smooth(40, 90, x))
  assert.equal(isBoxCut(measureAlpha(beam, W, H, FOOTPRINT)), false)
})

test('particles spread evenly into every corner of a rectangle fill it; a disc of them does not', () => {
  const dots = (weight: (x: number, y: number) => number) => paint((x, y) => (x * 7 + y * 13) % 11 < 4 ? 220 * weight(x, y) : 0)
  const rectangle = dots((x, y) => x > 70 && x < 250 && y > 30 && y < 150 ? 1 : 0)
  // the same scatter thinning out toward the rim of an ellipse, as the fixed particle painter does
  const disc = dots((x, y) => 1 - smooth(.7, 1, Math.hypot((x - 160) / 90, (y - 90) / 60)))
  assert.ok(cornerFill(rectangle, W, H, FOOTPRINT) >= CORNER_LIMIT, `rectangle ${cornerFill(rectangle, W, H, FOOTPRINT)}`)
  assert.ok(cornerFill(disc, W, H, FOOTPRINT) < CORNER_LIMIT, `disc ${cornerFill(disc, W, H, FOOTPRINT)}`)
  assert.equal(isBoxCut(measureAlpha(rectangle, W, H, FOOTPRINT), cornerFill(rectangle, W, H, FOOTPRINT)), true)
  assert.equal(isBoxCut(measureAlpha(disc, W, H, FOOTPRINT), cornerFill(disc, W, H, FOOTPRINT)), false)
})

test('an effect that fills the frame is a screen effect, with no footprint to end against', () => {
  const wash = paint(() => 90)
  const measure = measureAlpha(wash, W, H, FOOTPRINT)
  assert.equal(measure.screen, true)
  assert.equal(isBoxCut(measure), false)
  assert.equal(measureAlpha(new Uint8Array(W * H), W, H, FOOTPRINT).box, null)
})

test('the scanner is a whole-frame effect: its hairlines and sweep run edge to edge wherever the cue is placed', () => {
  assert.equal(coversFrame('scanline'), true)
  const drawn: Array<[number, number]> = []
  const state: Record<string, unknown> = { globalAlpha: 1, lineWidth: 1, strokeStyle: '', lineCap: 'butt' }
  const ctx = new Proxy(state, {
    get: (target, prop) => prop === 'moveTo' || prop === 'lineTo' ? (x: number, y: number) => { drawn.push([x, y]) } : typeof prop === 'string' && !(prop in target) ? () => {} : target[prop as string],
    set: (target, prop, value) => { target[prop as string] = value; return true },
  }) as unknown as CanvasRenderingContext2D
  const cue = parseSceneFx([{ id: 'scan', kind: 'scanline', start: 0, end: 4, x: 20, y: 30, size: 40, sound: false }])[0]
  paintSceneFx(ctx, 1280, 720, 1.2, [cue])
  const xs = new Set(drawn.map(([x]) => x))
  assert.deepEqual([...xs].sort((a, b) => a - b), [0, 1280], 'every line spans the frame')
  const ys = drawn.map(([, y]) => y)
  assert.ok(Math.min(...ys) < 8 && Math.max(...ys) > 712, 'the hairlines cover the frame top to bottom')
})
