import assert from 'node:assert/strict'
import test from 'node:test'
import { derivedTextMotion, displayedKineticText, KINETIC_TEXT_SCHEMA, kineticTextState, paintKineticTexts, parseKineticTexts, wrapKineticLines } from '../src/lib/kineticText.ts'
import type { KineticText } from '../src/lib/kineticText.ts'

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value))

function oracle(cue: Pick<KineticText, 'preset' | 'text' | 'start' | 'end'>, seconds: number) {
  const elapsed = seconds - cue.start
  const enter = clamp(elapsed / Math.min(.65, (cue.end - cue.start) / 3), 0, 1)
  const exit = clamp((cue.end - seconds) / Math.min(.3, (cue.end - cue.start) / 3), 0, 1)
  const impact = .65 * (1 - enter) ** 2 * Math.cos(enter * Math.PI * 3)
  return {
    opacity: Math.min(1, enter * 5) * exit,
    scale: cue.preset === 'impact' ? 1 + impact : 1,
    dy: cue.preset === 'rise' ? (1 - enter) ** 3 * .22 : 0,
    letters: cue.preset === 'typewriter' ? Math.ceil(Array.from(cue.text).length * clamp(elapsed / Math.min(1.7, (cue.end - cue.start) * .65), 0, 1)) : Array.from(cue.text).length,
  }
}

test('v1 cues stay inside the old limits and the old motion', () => {
  assert.equal(KINETIC_TEXT_SCHEMA.maxItems, 48)
  const cues = parseKineticTexts([
    ...['impact', 'rise', 'typewriter', 'wave'].map(preset => ({ id: preset, text: 'Ab', start: 0, end: 4, preset })),
    { id: 'long', text: 'x'.repeat(241), start: 0, end: 1, preset: 'impact' },
    ...Array.from({ length: 50 }, (_, index) => ({ id: `n${index}`, text: 'ok', start: 0, end: 1, preset: 'impact' })),
  ])
  assert.equal(cues.some(cue => cue.id === 'long'), false)
  assert.equal(parseKineticTexts(Array.from({ length: 60 }, (_, index) => ({ id: `c${index}`, text: 'a', start: 0, end: 1, preset: 'impact' }))).length, 48)
  assert.deepEqual(derivedTextMotion('impact'), { enter: 'impact', loop: 'none', exit: 'fade', exitSeconds: 0.3 })
  assert.deepEqual(derivedTextMotion('rise'), { enter: 'rise', loop: 'none', exit: 'fade', exitSeconds: 0.3 })
  assert.deepEqual(derivedTextMotion('typewriter'), { enter: 'typewriter', loop: 'none', exit: 'fade', exitSeconds: 0.3 })
  assert.deepEqual(derivedTextMotion('wave'), { enter: 'none', loop: 'wave', exit: 'fade', exitSeconds: 0.3 })
  for (const cue of cues.filter(item => ['impact', 'rise', 'typewriter', 'wave'].includes(item.id))) {
    for (const seconds of [0.1, 0.5, 2, 3.85]) {
      const state = kineticTextState(cue, seconds)
      assert.ok(state)
      const expected = oracle(cue, seconds)
      assert.equal(state.opacity, expected.opacity)
      assert.equal(state.scale, expected.scale)
      assert.equal(state.dy, expected.dy)
      assert.equal(state.letters, expected.letters)
    }
  }
})

test('v2 fields are optional, bounded, and drive wrapping and counters', () => {
  const cue = parseKineticTexts([{
    id: 'year', text: 'Año {value}', start: 0, end: 4, preset: 'impact', font: 'display',
    enter: { preset: 'words', duration: 1 }, exit: { preset: 'fade', duration: 0.3 }, loop: 'pulse',
    maxWidth: 40, uppercase: true, counter: { from: 1990, to: 2000, decimals: 0, ease: 'linear' },
    box: { kind: 'paper', color: '#f3e6cf', opacity: 0.9, padding: 0.4 },
    weight: 400, align: 'center',
  }])[0]
  assert.equal(cue.font, 'display')
  assert.equal(cue.maxWidth, 40)
  assert.equal(displayedKineticText(cue, 2), 'AÑO 1995')
  const early = kineticTextState(cue, 0.2)
  assert.ok(early && 'clip' in early)
  assert.equal(early.letters, 1)
  const ctx = { measureText: (text: string) => ({ width: text.length * 10 }) } as unknown as CanvasRenderingContext2D
  assert.deepEqual(wrapKineticLines(ctx, 'aa bb cc', 50), ['aa bb', 'cc'])
  assert.equal(parseKineticTexts([{ id: 'bad', text: 'x', start: 0, end: 1, preset: 'impact', enter: { preset: 'nope', duration: 9 } }])[0].enter, undefined)
})

type Matrix = { a: number; b: number; c: number; d: number; e: number; f: number }

function inkBounds(cue: KineticText, width = 400, height = 100) {
  const pixels = new Uint8Array(width * height)
  let matrix: Matrix = { a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 }
  const stack: Matrix[] = []
  const mark = (x: number, y: number) => {
    const px = Math.round(x)
    const py = Math.round(y)
    if (px >= 0 && py >= 0 && px < width && py < height) pixels[py * width + px] = 1
  }
  const ctx = {
    font: '16px sans-serif', textAlign: 'left' as CanvasTextAlign, textBaseline: 'alphabetic' as CanvasTextBaseline,
    fillStyle: '#fff', strokeStyle: '#000', lineWidth: 1, globalAlpha: 1, filter: 'none', letterSpacing: '0px', lineJoin: 'round' as CanvasLineJoin,
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
    measureText(text: string) { return { width: Array.from(text).length * 10 } },
    beginPath() {}, closePath() {}, moveTo() {}, lineTo() {}, arcTo() {}, rect() {}, clip() {}, fill() {}, fillRect() {}, strokeText() {},
    createLinearGradient() { return { addColorStop() {} } },
    fillText(text: string, x: number, y: number) {
      const textWidth = Array.from(text).length * 10
      const start = this.textAlign === 'center' ? x - textWidth / 2 : this.textAlign === 'right' ? x - textWidth : x
      for (let index = 0; index < textWidth; index += 1) mark(matrix.a * (start + index) + matrix.c * y + matrix.e, matrix.b * (start + index) + matrix.d * y + matrix.f)
    },
  }
  paintKineticTexts(ctx as unknown as CanvasRenderingContext2D, width, height, 1.2, [cue])
  let min = width
  let max = -1
  for (let index = 0; index < pixels.length; index += 1) {
    if (!pixels[index]) continue
    const x = index % width
    if (x < min) min = x
    if (x > max) max = x
  }
  return { min, max }
}

function placed(align?: 'left' | 'center' | 'right', font?: 'display' | 'sans') {
  return parseKineticTexts([{
    id: 'date', text: 'STORY LAB', start: 0, end: 4, preset: 'impact', x: 30, y: 50, size: 10,
    ...(font ? { font } : {}),
    ...(align ? { align } : {}),
    enter: { preset: 'none', duration: 0.2 }, exit: { preset: 'none', duration: 0.2 },
  }])[0]
}

test('left and right text sit on x while center and omitted align stay centered', () => {
  const anchor = 400 * 0.3
  const width = 9 * 10
  const left = inkBounds(placed('left', 'display'))
  const center = inkBounds(placed('center', 'display'))
  const omitted = inkBounds(placed(undefined, 'display'))
  const legacy = inkBounds(parseKineticTexts([{ id: 'date', text: 'STORY LAB', start: 0, end: 4, preset: 'impact', x: 30, y: 50, size: 10 }])[0])
  const right = inkBounds(placed('right', 'display'))
  assert.ok(Math.abs(left.min - anchor) <= 1, `left edge ${left.min}`)
  assert.ok(Math.abs(center.min - (anchor - width / 2)) <= 1, `center edge ${center.min}`)
  assert.equal(omitted.min, center.min)
  assert.equal(legacy.min, center.min)
  assert.ok(Math.abs(right.max - (anchor - 1)) <= 1, `right edge ${right.max}`)
})

test('tape width is measured with the same letter spacing used to paint its glyphs', () => {
  const measuredSpacing: string[] = []
  let tapeWidth = 0
  const ctx = {
    letterSpacing: '0em', globalAlpha: 1, fillStyle: '', strokeStyle: '', shadowColor: '', shadowBlur: 0,
    shadowOffsetX: 0, shadowOffsetY: 0, lineWidth: 0, textAlign: 'center', lineJoin: 'round',
    save() {}, restore() {}, translate() {}, rotate() {}, scale() {}, beginPath() {}, closePath() {},
    moveTo() {}, arcTo() {}, fill() {}, strokeText() {}, fillText() {},
    measureText(text: string) {
      measuredSpacing.push(this.letterSpacing)
      return { width: text.length * (10 + (this.letterSpacing === '0.1em' ? 5 : 0)) }
    },
  } as unknown as CanvasRenderingContext2D
  const originalMove = ctx.moveTo.bind(ctx)
  ctx.moveTo = (x: number, _y: number) => { if (!tapeWidth) tapeWidth = Math.abs(x) * 2; originalMove(x, _y) }
  const cue = parseKineticTexts([{ id: 'tape', text: 'OPEN', start: 0, end: 4, preset: 'impact',
    x: 50, y: 50, size: 10, letterSpacing: 0.1, enter: { preset: 'none', duration: 0.1 },
    box: { kind: 'tape', color: '#ffffff', opacity: 1, padding: 0.2 } }])[0]
  paintKineticTexts(ctx, 400, 100, 1, [cue])
  assert.ok(measuredSpacing.length > 0)
  assert.ok(measuredSpacing.every(spacing => spacing === '0.1em'))
  assert.ok(tapeWidth > 55, `tape width ${tapeWidth}`)
})
