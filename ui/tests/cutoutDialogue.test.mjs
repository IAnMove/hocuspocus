import assert from 'node:assert/strict'
import test from 'node:test'
import { applyCutoutDialogue, bindCutoutFaceToPose, ensureCutoutFacePlayback, findCutoutMouthLayers, normalizeAlignedCutoutUnits, normalizeFaceBinding, planAlignedCutoutDialogue, planCutoutDialogue, rebuildCutoutDialogueLayers, visemeForToken } from '../src/lib/cutoutDialogue.ts'
import { evaluateSceneLayer } from '../src/lib/sceneTimeline.ts'

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
  const open = plan.visemes.find(beat => beat.state !== 'closed')
  assert.ok(open && open.end - open.start > 0.12)
})

test('spoken tokens pick Spanish and English vowels; consonants are not silence', () => {
  assert.equal(visemeForToken('la'), 'wide')
  assert.equal(visemeForToken('hielo'), 'round')
  assert.equal(visemeForToken('you'), 'round')
  assert.equal(visemeForToken('see'), 'small')
  assert.equal(visemeForToken('cat'), 'wide')
  assert.equal(visemeForToken('sticker'), 'wide')
})

test('aligned words stay open during speech and close in the gaps', () => {
  const plan = planAlignedCutoutDialogue([
    { text: 'Era', start: 10, end: 10.3 },
    { text: 'un', start: 10.3, end: 10.52 },
    { text: 'sticker', start: 10.52, end: 10.96 },
  ], 30)
  const at = time => plan.visemes.find(beat => time >= beat.start && time < beat.end)?.state
  assert.equal(at(1), 'closed')
  assert.equal(at(10.15), 'wide')
  assert.equal(at(10.4), 'round')
  assert.equal(at(10.7), 'wide')
  assert.equal(plan.visemes.at(-1).state, 'closed')
  const starts = plan.visemes.map(beat => beat.start)
  assert.equal(new Set(starts).size, starts.length)
})

test('aligned word edits are ordered without extending a short word into silence', () => {
  const source = [{ text: 'you', start: 4, end: 4.02 }, { text: 'la', start: 1, end: 1.2 }]
  const plan = planAlignedCutoutDialogue(source, 30)
  assert.equal(plan.start, 1)
  assert.equal(plan.end, 4.02)
  assert.equal(source[0].start, 4, 'source word order is not mutated')
  assert.equal(plan.visemes[0].start, 0)
  assert.equal(plan.visemes[0].state, 'closed')
  assert.ok(plan.visemes.every(beat => beat.end <= 4.02))
  assert.ok(plan.visemes.every((beat, index) => !index || beat.start >= plan.visemes[index - 1].end))
})

test('audio alignment uses the track offset once, preserves text and excludes unusable scene intervals', () => {
  const units = normalizeAlignedCutoutUnits([
    { text: '  Hola! ', start: 0, end: .4 },
    { text: 'end', start: .8, end: 1.4 },
    { text: 'beyond', start: 2, end: 3 },
    { text: ' ', start: .2, end: .4 },
    { text: 'invalid', start: NaN, end: .4 },
    { text: 'empty', start: .2, end: .2 },
  ], 5, 6)
  assert.deepEqual(units, [{ text: '  Hola! ', start: 5, end: 5.4 }, { text: 'end', start: 5.8, end: 6 }])
  assert.deepEqual(normalizeAlignedCutoutUnits([{ text: 'clipped', start: 0, end: .4 }], -.2, 6),
    [{ text: 'clipped', start: 0, end: .2 }])
})

test('overlapping aligned words produce ordered, non-overlapping mouth states', () => {
  const plan = planAlignedCutoutDialogue([
    { text: 'la', start: 1, end: 1.5 }, { text: 'you', start: 1.2, end: 1.4 },
  ])
  assert.deepEqual(plan.visemes.filter(beat => beat.state !== 'closed'), [
    { start: 1, end: 1.2, state: 'wide' }, { start: 1.2, end: 1.4, state: 'round' },
  ])
  assert.equal(plan.visemes.at(-1).state, 'closed')
})

test('aligned rest closed is a distinct keyframe so playback does not hold the first word open', () => {
  const closed = {
    id: 'mouth-closed', name: 'Closed', type: 'overlay',
    transform: { x: 50, y: 48, scale: .12, opacity: 0, rotation: 0 },
    animation: { start: { x: 50, y: 48, scale: .12, opacity: 0 }, end: { x: 50, y: 48, scale: .12, opacity: 0 }, duration: 20, curve: 'hold' },
    faceBinding: { poseLayerId: 'pose', role: 'mouth', state: 'closed' },
  }
  const wide = {
    ...closed, id: 'mouth-wide', name: 'Wide',
    faceBinding: { poseLayerId: 'pose', role: 'mouth', state: 'wide' },
  }
  const beats = [
    { id: 'w0', text: 'La', start: 6, end: 6.14, mouthLayerIds: [closed.id, wide.id], confidence: 'aligned-audio' },
    { id: 'w1', text: 'fuente', start: 6.14, end: 6.56, mouthLayerIds: [closed.id, wide.id], confidence: 'aligned-audio' },
  ]
  const rebuilt = rebuildCutoutDialogueLayers([closed, wide], beats, 30, 20)
  const closedLayer = rebuilt.find(item => item.id === closed.id)
  const wideLayer = rebuilt.find(item => item.id === wide.id)
  assert.equal(evaluateSceneLayer(closedLayer, 1).opacity, 1)
  assert.equal(evaluateSceneLayer(wideLayer, 1).opacity, 0)
  assert.equal(evaluateSceneLayer(wideLayer, 6.05).opacity, 1)
  assert.equal(evaluateSceneLayer(closedLayer, 6.05).opacity, 0)
})

test('a later turn does not close the same speaker first word at scene zero', () => {
  const mouths = ['a', 'b'].flatMap(pose => ['closed', 'wide'].map(state => ({
    ...layer(`${pose}-mouth-${state}`), type: 'overlay',
    faceBinding: { poseLayerId: pose, role: 'mouth', state },
  })))
  const beats = [
    { id: 'a1', text: 'la', start: 0, end: .4, mouthLayerIds: ['a-mouth-closed', 'a-mouth-wide'], confidence: 'aligned-audio' },
    { id: 'b1', text: 'la', start: 1, end: 1.4, mouthLayerIds: ['b-mouth-closed', 'b-mouth-wide'], confidence: 'aligned-audio' },
    { id: 'a2', text: 'la', start: 2, end: 2.4, mouthLayerIds: ['a-mouth-closed', 'a-mouth-wide'], confidence: 'aligned-audio' },
  ]
  const result = rebuildCutoutDialogueLayers(mouths, beats, 30, 5)
  const wide = result.find(item => item.id === 'a-mouth-wide')
  assert.equal(evaluateSceneLayer(wide, .1).opacity, 1)
  assert.equal(evaluateSceneLayer(wide, 1.1).opacity, 0)
  assert.equal(evaluateSceneLayer(wide, 2.1).opacity, 1)
})

test('a long mixed-vowel line retains every available mouth family', () => {
  const plan = planCutoutDialogue('La antena envía una curiosa señal de sopa.', 0, 3.1, 30)
  assert.ok(plan.visemes.some(beat => beat.state === 'small'))
  assert.ok(plan.visemes.some(beat => beat.state === 'wide'))
  assert.ok(plan.visemes.some(beat => beat.state === 'round'))
})

test('dialogue keyframes copy the mounted mouth transform instead of a 50/50 rest pose', () => {
  const mounted = {
    id: 'kit-luma-mouth-wide',
    name: 'Luma Mouth wide',
    type: 'overlay',
    transform: { x: 32, y: 48.08, scale: .0434, opacity: 0, rotation: 0 },
    animation: { start: { x: 50, y: 50, scale: 1, opacity: 0 }, end: { x: 50, y: 50, scale: 1, opacity: 0 }, duration: 5, curve: 'hold' },
    faceBinding: { poseLayerId: 'kit-luma-pose-base', role: 'mouth', state: 'wide' },
  }
  const closed = {
    ...mounted,
    id: 'kit-luma-mouth-closed',
    name: 'Luma Mouth closed',
    transform: { ...mounted.transform, opacity: 1 },
    faceBinding: { poseLayerId: 'kit-luma-pose-base', role: 'mouth', state: 'closed' },
  }
  const plan = { start: 0, end: 1, visemes: [{ start: 0, end: .4, state: 'closed' }, { start: .4, end: 1, state: 'wide' }] }
  const frames = applyCutoutDialogue({ closed, wide: mounted }, plan)
  assert.ok(frames['kit-luma-mouth-wide'].every(frame => frame.x === 32 && frame.y === 48.08 && frame.scale === .0434))
  assert.ok(frames['kit-luma-mouth-closed'].every(frame => frame.x === 32 && frame.y === 48.08 && frame.scale === .0434))
  assert.deepEqual(frames['kit-luma-mouth-wide'].map(frame => frame.opacity), [0, 1, 0])
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

test('playback fills talking and blink keyframes when the kit is still at rest', () => {
  const closed = {
    id: 'kit-luma-mouth-closed', name: 'Luma Mouth closed', type: 'overlay',
    transform: { x: 32, y: 48, scale: .05, opacity: 1, rotation: 0 },
    animation: { start: { x: 32, y: 48, scale: .05, opacity: 1 }, end: { x: 32, y: 48, scale: .05, opacity: 1 }, duration: 6, curve: 'hold' },
    faceBinding: { poseLayerId: 'pose', role: 'mouth', state: 'closed' },
  }
  const wide = {
    ...closed, id: 'kit-luma-mouth-wide', name: 'Luma Mouth wide',
    transform: { ...closed.transform, opacity: 0 },
    animation: { start: { x: 32, y: 48, scale: .05, opacity: 0 }, end: { x: 32, y: 48, scale: .05, opacity: 0 }, duration: 6, curve: 'hold' },
    faceBinding: { poseLayerId: 'pose', role: 'mouth', state: 'wide' },
  }
  const blink = {
    ...closed, id: 'kit-luma-eyes-blink', name: 'Luma Eyes blink',
    transform: { ...closed.transform, opacity: 0, y: 40 },
    animation: { start: { x: 32, y: 40, scale: .12, opacity: 0 }, end: { x: 32, y: 40, scale: .12, opacity: 0 }, duration: 6, curve: 'hold' },
    faceBinding: { poseLayerId: 'pose', role: 'blink', state: 'blink' },
  }
  const open = {
    ...blink, id: 'kit-luma-eyes-open', name: 'Luma Eyes open',
    transform: { ...blink.transform, opacity: 1 },
    animation: { start: { x: 32, y: 40, scale: .12, opacity: 1 }, end: { x: 32, y: 40, scale: .12, opacity: 1 }, duration: 6, curve: 'hold' },
    faceBinding: { poseLayerId: 'pose', role: 'eyes', state: 'open' },
  }
  // Import must retain the open-eye state, otherwise playback cannot hide it
  // while the closed-eye overlay is visible.
  const imported = [closed, wide, blink, open].map(layer => ({
    ...layer, faceBinding: normalizeFaceBinding(layer.faceBinding),
  }))
  assert.equal(imported.at(-1).faceBinding.state, 'open')
  const silent = ensureCutoutFacePlayback(imported, 6, 30)
  for (let frame = 0; frame <= 180; frame += 1) {
    const at = id => evaluateSceneLayer(silent.find(layer => layer.id === id), frame / 30).opacity
    assert.equal(at(closed.id), 1, 'a silent character keeps the closed mouth')
    assert.equal(at(wide.id), 0, 'no fabricated speech during silence')
    assert.equal(at(blink.id) + at(open.id), 1, 'exactly one eye state at each frame')
  }
  const next = ensureCutoutFacePlayback(imported, 6, 30, [], 'Hola, una frase explícita.')
  const closedFrames = next.find(layer => layer.id === closed.id).animation.keyframes
  const wideFrames = next.find(layer => layer.id === wide.id).animation.keyframes
  const blinkFrames = next.find(layer => layer.id === blink.id).animation.keyframes
  const openFrames = next.find(layer => layer.id === open.id).animation.keyframes
  assert.ok(closedFrames.some(frame => frame.opacity === 0))
  assert.ok(wideFrames.some(frame => frame.opacity === 1))
  assert.ok(wideFrames.every(frame => frame.x === 32 && frame.y === 48))
  assert.ok(blinkFrames.some(frame => frame.opacity === 1))
  assert.ok(openFrames.some(frame => frame.opacity === 0))
})
