import assert from 'node:assert/strict'
import test from 'node:test'
import { applyCutoutDialogue, bindCutoutFaceToPose, findCutoutMouthLayers, planCutoutDialogue, rebuildCutoutDialogueLayers } from '../src/lib/cutoutDialogue.ts'

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

test('semantic face binding wins over names and keeps pose assignments isolated', () => {
  const poseA = { ...layer('pose-a'), name: 'Character pose A', type: 'image' }
  const poseB = { ...layer('pose-b'), name: 'Character pose B', type: 'image' }
  const mouthA = { ...layer('overlay-a'), name: 'Overlay A', type: 'overlay', faceBinding: { poseLayerId: poseA.id, role: 'mouth', state: 'wide' } }
  const mouthB = { ...layer('overlay-b'), name: 'Overlay B', type: 'overlay', faceBinding: { poseLayerId: poseB.id, role: 'mouth', state: 'small' } }
  const blinkB = { ...layer('eyes-b'), name: 'Eyes B', type: 'overlay', faceBinding: { poseLayerId: poseB.id, role: 'blink', state: 'blink' } }
  const found = findCutoutMouthLayers([poseA, poseB, mouthA, mouthB, blinkB])
  assert.equal(found.wide?.id, mouthA.id)
  assert.equal(found.small?.id, mouthB.id)
  const foundB = findCutoutMouthLayers([poseA, poseB, mouthA, mouthB, blinkB], poseB.id)
  assert.equal(foundB.open?.id, mouthB.id)
  assert.equal(foundB.small?.id, mouthB.id)
  assert.equal(foundB.wide, undefined)
  const boundA = bindCutoutFaceToPose([poseA, poseB, mouthA, mouthB, blinkB], poseA.id)
  assert.deepEqual(boundA.find(item => item.id === mouthA.id).relationship, { type: 'parent', targetLayerId: poseA.id })
  assert.deepEqual(boundA.find(item => item.id === mouthB.id).relationship, undefined)
  assert.deepEqual(boundA.find(item => item.id === blinkB.id).relationship, undefined)
})

test('a selected character without assigned mouths does not reuse another character mouth kit', () => {
  const poseA = { ...layer('pose-a'), name: 'Character A pose', type: 'image' }
  const poseB = { ...layer('pose-b'), name: 'Character B pose', type: 'image' }
  const mouthA = { ...layer('mouth-a-wide'), name: 'Character A wide mouth', type: 'overlay', faceBinding: { poseLayerId: poseA.id, role: 'mouth', state: 'wide' } }

  const foundForB = findCutoutMouthLayers([poseA, poseB, mouthA], poseB.id)

  assert.ok(Object.values(foundForB).every(value => value === undefined))
})

test('legacy single-character scenes still discover unbound mouths', () => {
  const pose = { ...layer('legacy-pose'), name: 'Legacy character pose', type: 'image' }
  const mouth = { ...layer('legacy-mouth-round'), name: 'Round mouth', type: 'overlay' }

  const found = findCutoutMouthLayers([pose, mouth], pose.id)

  assert.equal(found.round?.id, mouth.id)
})

test('legacy unparented overlays receive semantic binding while legacy other-pose parents stay untouched', () => {
  const pose = { ...layer('pose'), name: 'Character pose', type: 'image' }
  const legacyMouth = { ...layer('mouth-open'), name: 'Open mouth', type: 'overlay' }
  const other = { ...layer('mouth-closed'), name: 'Closed mouth', type: 'overlay', relationship: { type: 'parent', targetLayerId: 'other-pose' } }
  const bound = bindCutoutFaceToPose([pose, legacyMouth, other], pose.id)
  assert.deepEqual(bound.find(item => item.id === legacyMouth.id).faceBinding, { poseLayerId: pose.id, role: 'mouth', state: 'wide' })
  assert.deepEqual(bound.find(item => item.id === other.id).relationship, { type: 'parent', targetLayerId: 'other-pose' })
})

test('editing dialogue speaker clears stale frames and rebuilds only the assigned mouth kit', () => {
  const poseA = { ...layer('pose-a'), name: 'A', type: 'image' }
  const poseB = { ...layer('pose-b'), name: 'B', type: 'image' }
  const mouthA = { ...layer('mouth-a-wide'), name: 'A wide', type: 'overlay', faceBinding: { poseLayerId: poseA.id, role: 'mouth', state: 'wide' }, animation: { ...layer('mouth-a-wide').animation, keyframes: [{ id: 'old', time: 0, x: 50, y: 48, scale: .12, opacity: 1 }] } }
  const mouthB = { ...layer('mouth-b-wide'), name: 'B wide', type: 'overlay', faceBinding: { poseLayerId: poseB.id, role: 'mouth', state: 'wide' } }
  const beats = [{ id: 'line', text: 'Ahora habla B', start: 1, end: 3, mouthLayerIds: [mouthB.id], confidence: 'known-text' }]
  const rebuilt = rebuildCutoutDialogueLayers([poseA, poseB, mouthA, mouthB], beats, 30, 5, [mouthA.id])
  assert.equal(rebuilt.find(item => item.id === mouthA.id).animation.keyframes, undefined)
  assert.ok(rebuilt.find(item => item.id === mouthB.id).animation.keyframes.some(frame => frame.opacity === 1))
})
