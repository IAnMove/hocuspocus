import assert from 'node:assert/strict'
import test from 'node:test'
import { buildTextTemplate, paintKineticTexts, parseKineticTexts } from '../src/lib/kineticText.ts'

const wide = { start: 0.4, duration: 3.2, width: 1280, height: 720 }
const tall = { ...wide, width: 720, height: 1280 }

test('older title templates keep their geometry', () => {
  assert.equal(buildTextTemplate('lower-third-date', {}, wide)[0].y, 70)
  assert.equal(buildTextTemplate('lower-third-date', {}, tall)[0].y, 64)
  assert.equal(buildTextTemplate('title-card', { title: 'Musktopia', subtitle: '' }, wide)[0].box?.kind, 'plate')
  assert.equal(buildTextTemplate('social-caption', {}, wide)[0].y, 84)
})

test('ransom puts one paper strip on each word', () => {
  const cues = buildTextTemplate('ransom', { line: 'THE BIRD IS FREED' }, wide)
  assert.deepEqual(cues.map(cue => cue.text), ['THE', 'BIRD', 'IS', 'FREED'])
  assert.deepEqual(cues.map(cue => cue.box?.kind), ['paper', 'paper', 'paper', 'paper'])
  assert.deepEqual(cues.map(cue => cue.rotation), [-3, 2, -1, 4])
  assert.deepEqual(cues.map(cue => cue.font), ['display', 'marker', 'serif', 'condensed'])
  assert.deepEqual(cues.map(cue => cue.x), [23, 41, 59, 77])
  assert.deepEqual(cues.map(cue => cue.y), [48, 48, 48, 48])
  assert.equal(cues[1].start, wide.start + 0.12)
  assert.equal(cues[3].end, wide.start + wide.duration)
  const portrait = buildTextTemplate('ransom', { line: 'THE BIRD IS FREED' }, tall)
  assert.deepEqual(portrait.map(cue => [cue.x, cue.y]), [[28, 40], [50, 40], [72, 40], [50, 52]])
  assert.equal(parseKineticTexts(cues).length, 4)
})

test('dymo cuts light letters from black tape and inks a colored tape on dark', () => {
  const paper = buildTextTemplate('dymo', { line: 'KEEP THE LINE', background: 'paper' }, wide)[0]
  const dark = buildTextTemplate('dymo', { line: 'keep the line', background: 'dark' }, wide)[0]
  assert.equal(paper.text, 'KEEP THE LINE')
  assert.equal(paper.box?.kind, 'tape')
  assert.equal(paper.box?.color, '#141210')
  assert.equal(paper.color, '#f4efe6')
  assert.equal(paper.font, 'mono')
  assert.equal(paper.y, 78)
  assert.equal(dark.text, 'KEEP THE LINE')
  assert.equal(dark.color, '#141210')
  assert.equal(dark.box?.color, '#f2b705')
  assert.equal(dark.rotation, paper.rotation)
  const portrait = buildTextTemplate('dymo', { line: 'KEEP THE LINE', background: 'paper' }, tall)[0]
  assert.equal(portrait.y, 72)
  assert.equal(portrait.maxWidth, 84)
  assert.equal(parseKineticTexts([dark])[0].box?.kind, 'tape')
})

test('card is one panel', () => {
  const cue = buildTextTemplate('card', { title: 'Musktopia' }, wide)[0]
  assert.equal(cue.box?.kind, 'card')
  assert.equal(cue.box?.color, '#f7f1e4')
  assert.equal(cue.rotation, -1)
  assert.equal(cue.y, 46)
  assert.equal(cue.size, 12)
  const portrait = buildTextTemplate('card', { title: 'Musktopia' }, tall)[0]
  assert.equal(portrait.y, 44)
  assert.equal(portrait.size, 10)
})

function recordingContext() {
  const ops: string[] = []
  let composite = 'source-over'
  const ctx = {
    font: '', textAlign: 'left' as CanvasTextAlign, textBaseline: 'alphabetic' as CanvasTextBaseline,
    fillStyle: '#fff', strokeStyle: '#000', lineWidth: 1, globalAlpha: 1, filter: 'none',
    letterSpacing: '0px', lineJoin: 'round' as CanvasLineJoin,
    shadowColor: 'transparent', shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
    get globalCompositeOperation() { return composite },
    set globalCompositeOperation(value: string) { composite = value; ops.push(`op:${value}`) },
    save() {}, restore() {}, translate() {}, scale() {}, rotate() {}, setTransform() {},
    measureText(text: string) { return { width: Array.from(text).length * 10 } },
    beginPath() {}, closePath() {}, moveTo() {}, lineTo() {}, arcTo() {}, rect() {}, clip() {},
    fill() { ops.push('fill') },
    stroke() { ops.push('stroke') },
    fillRect() {},
    arc() { ops.push('dot') },
    strokeText() {},
    fillText(text: string) { if (text) ops.push(`text:${composite}`) },
    createLinearGradient() { return { addColorStop() {} } },
  }
  return { ctx: ctx as unknown as CanvasRenderingContext2D, ops }
}

test('dymo punches light letters and card paints a halftone shadow', () => {
  const paper = recordingContext()
  paintKineticTexts(paper.ctx, 1280, 720, 2, buildTextTemplate('dymo', { line: 'KEEP THE LINE', background: 'paper' }, wide))
  assert.ok(paper.ops.includes('text:destination-out'))
  const dark = recordingContext()
  paintKineticTexts(dark.ctx, 1280, 720, 2, buildTextTemplate('dymo', { line: 'KEEP THE LINE', background: 'dark' }, wide))
  assert.equal(dark.ops.includes('text:destination-out'), false)
  assert.ok(dark.ops.includes('text:source-over'))
  const card = recordingContext()
  paintKineticTexts(card.ctx, 1280, 720, 2, buildTextTemplate('card', { title: 'Musktopia' }, wide))
  assert.ok(card.ops.includes('dot'))
  assert.ok(card.ops.includes('stroke'))
  assert.ok(card.ops.includes('text:source-over'))
})
