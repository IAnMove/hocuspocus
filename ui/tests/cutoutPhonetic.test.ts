import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit, mountCharacterKitLayers } from '../src/lib/characterKit'
import { CHARACTER_MOUTH_STATES } from '../src/lib/characterMouthStates'
import { rebuildCutoutDialogueLayers, type SceneDialogueBeat } from '../src/lib/cutoutDialogue'
import { currentCutoutLipSync, parseCutoutLipSync, planPhoneticCutoutDialogue } from '../src/lib/cutoutPhonetic'
import { evaluateSceneLayer } from '../src/lib/sceneTimeline'
import { parseSceneFile, serializeSceneFile } from '../src/lib/sceneFile'
import type { Scene } from '../src/types'

function rig(extended = true) {
  const kit = createCharacterKit('Actor')
  kit.base = { id: 'base', name: 'Actor', source: '/base.png', kind: 'image', alphaStatus: 'transparent', reviewState: 'approved' }
  for (const state of extended ? CHARACTER_MOUTH_STATES : CHARACTER_MOUTH_STATES.slice(0, 4)) {
    kit.mouth[state] = { ...kit.base, id: state, source: `/${state}.png`, kind: 'overlay' }
  }
  const layers = mountCharacterKitLayers(kit)
  const beat: SceneDialogueBeat = { id: 'line', text: 'Move, Phil.', start: 1, end: 3, audioTrackId: 'voice',
    mouthLayerIds: layers.filter(layer => layer.faceBinding?.role === 'mouth').map(layer => layer.id), confidence: 'aligned-audio',
    lipSync: { version: 1, driver: 'phonetic', text: 'Move, Phil.', audioTrackId: 'voice', filename: 'voice.wav', offset: 0, duration: 2,
      cues: [{ start: .1, end: .18, viseme: 'M' }, { start: .18, end: .75, viseme: 'U' },
        { start: 1.1, end: 1.2, viseme: 'F' }, { start: 1.2, end: 1.5, viseme: 'I' }, { start: 1.5, end: 1.8, viseme: 'L' }] } }
  return { layers, beat }
}

test('real durations preserve an 80ms bilabial closure, a held vowel and the actual silent gap', () => {
  const { layers, beat } = rig()
  const result = rebuildCutoutDialogueLayers(layers, [beat], 30, 4)
  const visible = (time: number) => result.filter(layer => layer.faceBinding?.role === 'mouth' && evaluateSceneLayer(layer, time).opacity === 1)
    .map(layer => layer.faceBinding!.state)
  for (const time of [0, .99, 1.9, 2.05, 3.5]) assert.deepEqual(visible(time), ['closed'])
  assert.deepEqual(visible(1.14), ['pressed'])
  assert.deepEqual(visible(1.6), ['pucker'])
  assert.deepEqual(visible(2.15), ['bite'])
  assert.deepEqual(visible(2.6), ['tongue'])
  assert.equal(planPhoneticCutoutDialogue(beat, 4)!.visemes.find(cue => cue.state === 'pucker')!.end, 1.75)
})

test('legacy four-mouth drawings retain phonetic timing and close for M/B/P', () => {
  const { layers, beat } = rig(false)
  const result = rebuildCutoutDialogueLayers(layers, [beat], 30, 4)
  const at = (time: number) => result.filter(layer => layer.faceBinding?.role === 'mouth' && evaluateSceneLayer(layer, time).opacity === 1).map(layer => layer.faceBinding!.state)
  assert.deepEqual(at(1.14), ['closed']); assert.deepEqual(at(1.6), ['round']); assert.deepEqual(at(2.15), ['small'])
})

test('editing text/audio or changing duration invalidates old analysis while moving the whole line keeps relative cues', () => {
  const { beat } = rig()
  assert.equal(currentCutoutLipSync({ ...beat, text: 'Different words' }), undefined)
  assert.equal(currentCutoutLipSync({ ...beat, audioTrackId: 'other' }), undefined)
  assert.equal(currentCutoutLipSync({ ...beat, end: 5 }), undefined)
  const moved = planPhoneticCutoutDialogue({ ...beat, start: 3, end: 5 }, 6)!
  assert.equal(moved.visemes.find(cue => cue.state === 'pressed')!.start, 3.1)
})

test('invalid cues cannot escape the fragment or overlap and saved scenes retain the phonetic track', () => {
  const { layers, beat } = rig()
  assert.throws(() => parseCutoutLipSync({ ...beat.lipSync, cues: [{ start: 0, end: 3, viseme: 'A' }] }), /exceed/)
  assert.throws(() => parseCutoutLipSync({ ...beat.lipSync, cues: [{ start: 0, end: 1, viseme: 'A' }, { start: .5, end: 1.5, viseme: 'O' }] }), /Overlapping/)
  const scene = { version: 1, width: 1280, height: 720, duration: 4, fps: 30, layers, dialogueBeats: [beat] } as Scene
  assert.deepEqual(parseSceneFile(serializeSceneFile(scene)).dialogueBeats, [beat])
})

test('a later turn cannot erase the first turn or animate the other character', () => {
  const { layers, beat } = rig()
  const second = { ...beat, id: 'second', start: 4, end: 6 }
  const result = rebuildCutoutDialogueLayers(layers, [beat, second], 30, 7)
  const pucker = result.find(layer => layer.faceBinding?.state === 'pucker')!
  for (const time of [1.6, 4.6]) assert.equal(evaluateSceneLayer(pucker, time).opacity, 1)
  assert.equal(evaluateSceneLayer(pucker, 3.5).opacity, 0)
})
