import assert from 'node:assert/strict'
import test from 'node:test'
import { applyCutoutDialogue, planCutoutDialogue } from '../src/lib/cutoutDialogue.ts'

const layer = id => ({ id, animation: { start: { x: 50, y: 48, scale: .12, opacity: 1 }, end: { x: 50, y: 48, scale: .12, opacity: 1 }, duration: 5, curve: 'hold' } })

test('cutout dialogue is bounded, begins and ends closed', () => {
  const plan = planCutoutDialogue('Hola, ¿cómo estás?', 1, 4, 30)
  assert.equal(plan.start, 1)
  assert.equal(plan.end, 4)
  assert.equal(plan.visemes[0].state, 'closed')
  assert.equal(plan.visemes.at(-1).state, 'closed')
  assert.ok(plan.visemes.some(beat => beat.state !== 'closed'))
  assert.ok(plan.visemes.every(beat => beat.start >= 1 && beat.end <= 4))
})

test('a short aligned word still gets one readable open pulse', () => {
  const plan = planCutoutDialogue('la', 1, 1.24, 30)
  assert.equal(plan.visemes[0].state, 'closed')
  assert.equal(plan.visemes.at(-1).state, 'closed')
  assert.ok(plan.visemes.some(beat => beat.state !== 'closed'))
})

test('mouth layers receive complementary, editable opacity keyframes', () => {
  const plan = planCutoutDialogue('Una frase corta para hablar.', 0, 3, 30)
  const frames = applyCutoutDialogue({ open: layer('mouth-open'), closed: layer('mouth-closed') }, plan)
  assert.equal(frames['mouth-open'][0].opacity, 0)
  assert.equal(frames['mouth-closed'][0].opacity, 1)
  assert.equal(frames['mouth-open'].at(-1).opacity, 0)
  assert.equal(frames['mouth-closed'].at(-1).opacity, 1)
  for (let index = 0; index < frames['mouth-open'].length; index += 1) {
    assert.equal(frames['mouth-open'][index].opacity + frames['mouth-closed'][index].opacity, 1)
  }
})
