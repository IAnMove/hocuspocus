import assert from 'node:assert/strict'
import test from 'node:test'
import { INK_TRAP_PAPER, inkTrapBox, inkTrapStroke } from '../src/lib/scene2d/inkTrap.ts'
import { isLegacyKineticText, KINETIC_TEXT_SCHEMA, paintKineticTexts, parseKineticTexts } from '../src/lib/kineticText.ts'
import type { KineticText } from '../src/lib/kineticText.ts'

const glyph = { x: 8, y: 10, width: 24, height: 36 }
const fontSize = 80

test('a colored glyph trap box grows by about 5% of the font size', () => {
  const trapped = inkTrapBox(glyph, fontSize, true, '#ff48b0')
  assert.ok(Math.abs(trapped.width - glyph.width - fontSize * 0.05) < 1e-9)
  assert.ok(Math.abs(trapped.height - glyph.height - fontSize * 0.05) < 1e-9)
  assert.equal(trapped.width - glyph.width, inkTrapStroke(fontSize))
  assert.equal(inkTrapBox(glyph, fontSize, false, '#ff48b0'), glyph)
  assert.equal(inkTrapBox(glyph, fontSize, true, '#1B1718'), glyph)
})

function cue(extra: Record<string, unknown> = {}): KineticText {
  return parseKineticTexts([{
    id: 'ink', text: 'A', start: 0, end: 4, preset: 'impact', x: 50, y: 50, size: 20, color: '#ff48b0',
    ...extra,
  }])[0]
}

function paperStrokes(cues: KineticText[], ink?: { riso?: boolean; paper?: string }) {
  const paper: number[] = []
  const ctx = {
    font: '', textAlign: 'left' as CanvasTextAlign, textBaseline: 'alphabetic' as CanvasTextBaseline,
    fillStyle: '#fff', strokeStyle: '#000', lineWidth: 1, globalAlpha: 1, filter: 'none', letterSpacing: '0px',
    lineJoin: 'round' as CanvasLineJoin, shadowColor: 'transparent', shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
    save() {}, restore() {}, translate() {}, scale() {}, rotate() {}, setTransform() {},
    measureText(text: string) { return { width: Array.from(text).length * 10 } },
    beginPath() {}, closePath() {}, moveTo() {}, lineTo() {}, arcTo() {}, rect() {}, clip() {}, fill() {}, fillRect() {},
    createLinearGradient() { return { addColorStop() {} } },
    strokeText() { if (this.strokeStyle === INK_TRAP_PAPER) paper.push(this.lineWidth) },
    fillText() {},
  }
  paintKineticTexts(ctx as unknown as CanvasRenderingContext2D, 800, 200, 1, cues, 0, ink)
  return paper
}

test('the painter reserves black only for colored type when trap or riso is on', () => {
  const drawn = 200 * 20 / 100
  const legacy = cue({ trap: true })
  assert.equal(legacy.trap, true)
  assert.equal(isLegacyKineticText(legacy), true)
  assert.equal(KINETIC_TEXT_SCHEMA.items.properties.trap.type, 'boolean')
  const on = paperStrokes([legacy])
  assert.equal(on.length, 1)
  assert.ok(Math.abs(on[0] - drawn * 0.05) < 1e-9)
  assert.equal(paperStrokes([cue()]).length, 0)
  assert.equal(paperStrokes([cue({ color: '#1B1718', trap: true })]).length, 0)
  const riso = paperStrokes([cue({ font: 'display', enter: { preset: 'none', duration: 0.2 }, exit: { preset: 'none', duration: 0.2 } })], { riso: true })
  assert.equal(riso.length, 1)
  assert.ok(Math.abs(riso[0] - drawn * 0.05) < 1e-9)
})
