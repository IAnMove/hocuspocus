import assert from 'node:assert/strict'
import test from 'node:test'
import { applyCutoutDialogue, bindCutoutFaceToPose, findCutoutMouthLayers, planCutoutDialogue } from '../src/lib/cutoutDialogue.ts'

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

test('a long mixed-vowel line retains every available mouth family', () => {
  const plan = planCutoutDialogue('La antena envía una curiosa señal de sopa.', 0, 3.1, 30)
  assert.ok(plan.visemes.some(beat => beat.state === 'small'))
  assert.ok(plan.visemes.some(beat => beat.state === 'wide'))
  assert.ok(plan.visemes.some(beat => beat.state === 'round'))
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

test('named mouth shapes receive their matching viseme with an open fallback', () => {
  const layers = {
    open: layer('mouth-open'), closed: layer('mouth-closed'),
    small: layer('mouth-small'), wide: layer('mouth-wide'), round: layer('mouth-round'),
  }
  const plan = {
    start: 0, end: 1,
    visemes: [
      { start: 0, end: .2, state: 'closed' },
      { start: .2, end: .4, state: 'small' },
      { start: .4, end: .6, state: 'wide' },
      { start: .6, end: .8, state: 'round' },
      { start: .8, end: 1, state: 'closed' },
    ],
  }
  const frames = applyCutoutDialogue(layers, plan)
  assert.deepEqual(frames['mouth-closed'].slice(0, 5).map(frame => frame.opacity), [1, 0, 0, 0, 1])
  assert.deepEqual(frames['mouth-small'].slice(0, 5).map(frame => frame.opacity), [0, 1, 0, 0, 0])
  assert.deepEqual(frames['mouth-wide'].slice(0, 5).map(frame => frame.opacity), [0, 0, 1, 0, 0])
  assert.deepEqual(frames['mouth-round'].slice(0, 5).map(frame => frame.opacity), [0, 0, 0, 1, 0])
  assert.ok(frames['mouth-open'].every(frame => frame.opacity === 0))
})

test('mouth discovery and pose binding preserve the authored face placement', () => {
  const pose = { ...layer('hero-pose-pointing'), name: 'Hero pointing pose', type: 'image' }
  const mouth = { ...layer('mouth-round'), name: 'Round mouth', type: 'overlay' }
  const eyes = { ...layer('blink-eyes'), name: 'Blink eyes', type: 'overlay' }
  const plate = { ...layer('plate'), name: 'Background plate', type: 'image' }
  const found = findCutoutMouthLayers([pose, mouth, eyes, plate])
  assert.equal(found.round?.id, mouth.id)
  const bound = bindCutoutFaceToPose([pose, mouth, eyes, plate], pose.id)
  assert.deepEqual(bound.find(item => item.id === mouth.id).relationship, { type: 'parent', targetLayerId: pose.id })
  assert.deepEqual(bound.find(item => item.id === eyes.id).relationship, { type: 'parent', targetLayerId: pose.id })
  assert.equal(bound.find(item => item.id === plate.id).relationship, undefined)
  assert.equal(bound.find(item => item.id === mouth.id).animation.start.x, mouth.animation.start.x)
})
