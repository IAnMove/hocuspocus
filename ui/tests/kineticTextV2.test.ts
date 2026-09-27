import assert from 'node:assert/strict'
import test from 'node:test'
import { derivedTextMotion, displayedKineticText, KINETIC_TEXT_SCHEMA, kineticTextState, parseKineticTexts, wrapKineticLines } from '../src/lib/kineticText.ts'
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
