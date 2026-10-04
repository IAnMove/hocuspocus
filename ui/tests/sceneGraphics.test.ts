import assert from 'node:assert/strict'
import test from 'node:test'
import { paintKineticTexts, parseKineticTexts } from '../src/lib/kineticText.ts'

type Matrix = { a: number; b: number; c: number; d: number; e: number; f: number }

function raster(width: number, height: number) {
  const pixels = new Uint8Array(width * height)
  let matrix: Matrix = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }
  const stack: Matrix[] = []
  let path: Array<{ x: number; y: number; r: number }> = []
  const mark = (x: number, y: number) => {
    const px = Math.round(x)
    const py = Math.round(y)
    if (px >= 0 && py >= 0 && px < width && py < height) pixels[py * width + px] = 1
  }
  const apply = (x: number, y: number) => [matrix.a * x + matrix.c * y + matrix.e, matrix.b * x + matrix.d * y + matrix.f]
  const ctx = {
    fillStyle: '#fff', strokeStyle: '#000', font: '16px sans-serif',
    textAlign: 'left' as CanvasTextAlign, textBaseline: 'alphabetic' as CanvasTextBaseline,
    lineWidth: 1, lineJoin: 'round' as CanvasLineJoin, globalAlpha: 1, filter: 'none', letterSpacing: '0px',
    shadowColor: 'transparent', shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
    save() { stack.push({ ...matrix }) },
    restore() { const previous = stack.pop(); if (previous) matrix = previous },
    translate(x: number, y: number) { matrix = { ...matrix, e: matrix.e + matrix.a * x + matrix.c * y, f: matrix.f + matrix.b * x + matrix.d * y } },
    scale(x: number, y: number) { matrix = { ...matrix, a: matrix.a * x, b: matrix.b * x, c: matrix.c * y, d: matrix.d * y } },
    rotate(angle: number) {
      const cos = Math.cos(angle)
      const sin = Math.sin(angle)
      matrix = { a: matrix.a * cos + matrix.c * sin, b: matrix.b * cos + matrix.d * sin, c: matrix.c * cos - matrix.a * sin, d: matrix.d * cos - matrix.b * sin, e: matrix.e, f: matrix.f }
    },
    setTransform(a = 1, b = 0, c = 0, d = 1, e = 0, f = 0) { matrix = { a, b, c, d, e, f } },
    beginPath() { path = [] },
    closePath() {}, moveTo() {}, lineTo() {}, arcTo() {}, rect() {}, clip() {}, stroke() {},
    arc(x: number, y: number, r: number) { path.push({ x, y, r }) },
    fill() {
      if (ctx.globalAlpha <= 0) return
      for (const item of path) stampDisc(item.x, item.y, item.r)
    },
    fillRect(x: number, y: number, w: number, h: number) {
      if (ctx.globalAlpha <= 0 || w === 0 || h === 0) return
      const x0 = Math.min(x, x + w)
      const y0 = Math.min(y, y + h)
      const x1 = Math.max(x, x + w)
      const y1 = Math.max(y, y + h)
      for (let py = y0; py <= y1; py += 1) {
        for (let px = x0; px <= x1; px += 1) {
          const [sx, sy] = apply(px, py)
          mark(sx, sy)
        }
      }
    },
    measureText(text: string) { return { width: Math.max(1, Array.from(text).length * 8) } },
    fillText() {}, strokeText() {},
    createLinearGradient() { return { addColorStop() {} } },
  }
  function stampDisc(x: number, y: number, r: number) {
    const radius = Math.max(0, r)
    for (let py = -radius; py <= radius; py += 1) {
      for (let px = -radius; px <= radius; px += 1) {
        if (px * px + py * py > radius * radius) continue
        const [sx, sy] = apply(x + px, y + py)
        mark(sx, sy)
      }
    }
  }
  return { ctx: ctx as unknown as CanvasRenderingContext2D, pixels }
}

function graphicCue(id: 'chart' | 'countdown') {
  return parseKineticTexts([{
    id, text: '', start: 0, end: 4, preset: 'impact', x: 50, y: 50, size: 40,
    graphic: { id, params: id === 'chart' ? { series: 'curve', points: 8 } : { from: 5 } },
  }])[0]
}

test('chart and countdown paint a non-empty pixel', () => {
  for (const id of ['chart', 'countdown'] as const) {
    const cue = graphicCue(id)
    assert.equal(cue.graphic?.id, id)
    const buffer = raster(64, 64)
    paintKineticTexts(buffer.ctx, 64, 64, 1.6, [cue])
    assert.equal(buffer.pixels.some(pixel => pixel > 0), true, id)
  }
})

test('a cue without graphic stays on the text painter', () => {
  const cue = parseKineticTexts([{ id: 'plain', text: 'Hi', start: 0, end: 4, preset: 'impact' }])[0]
  assert.equal(cue.graphic, undefined)
  let rects = 0
  const ctx = {
    save() {}, restore() {}, translate() {}, rotate() {}, scale() {},
    measureText(text: string) { return { width: text.length * 10 } },
    fillText() {}, strokeText() {}, fillRect() { rects += 1 },
  }
  paintKineticTexts(ctx as unknown as CanvasRenderingContext2D, 200, 80, 1, [cue])
  assert.equal(rects, 0)
  assert.equal(parseKineticTexts([{ id: 'bad', text: 'a', start: 0, end: 1, preset: 'impact', graphic: { id: 'custom-js' } }])[0].graphic, undefined)
})

test('tiling paints a full-frame desktop whose windows open one after another', () => {
  const cue = parseKineticTexts([{
    id: 'desk', text: '', start: 0, end: 8, preset: 'impact', x: 50, y: 50, size: 10,
    graphic: { id: 'tiling', params: { theme: 'tokyo-night', layout: 'quad', apps: 'mixed' } },
  }])[0]
  assert.equal(cue.graphic?.id, 'tiling')
  const covered = (seconds: number) => {
    const buffer = raster(160, 90)
    paintKineticTexts(buffer.ctx, 160, 90, seconds, [cue])
    return buffer.pixels.reduce((sum, pixel) => sum + pixel, 0)
  }
  const early = covered(0.05)
  const late = covered(6)
  assert.ok(early > 160 * 90 * 0.9, 'the wallpaper and bar fill the frame from the first frame')
  assert.equal(late >= early, true)
  assert.equal(parseKineticTexts([{ id: 'x', text: '', start: 0, end: 1, preset: 'impact', graphic: { id: 'tiling', params: { theme: 'nope' } } }])[0].graphic?.params?.theme, 'tokyo-night')
})
