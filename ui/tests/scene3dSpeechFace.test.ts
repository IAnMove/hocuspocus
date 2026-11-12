import assert from 'node:assert/strict'
import test from 'node:test'
import { Object3D } from 'three'
import { speechFace } from '../src/features/scene3d/speech/runtime'
import type { FacePlacement, Scene3DSpeech } from '../src/features/scene3d/speech/types'

const face = (meshIndex: number): FacePlacement => ({
  meshIndex, center: [0, 1, 0], size: [.2, .2], skin: [1, .8, .4],
  eyes: { left: [-.1, 1.2, 0], right: [.1, 1.2, 0], size: [.1, .06], skinLeft: [1, .8, .4], skinRight: [1, .8, .4] },
})
const speech = (extra: Partial<Scene3DSpeech>): Scene3DSpeech => ({ version: 1, enabled: true, cues: [], driver: 'imported', start: 0, offset: 0, gain: 1, strength: .85, clean: false, style: 'soft', lip: '#874d47', expression: 'neutral', blink: true, eyes: false, ...extra }) as Scene3DSpeech
const model = (estimate?: FacePlacement) => { const root = new Object3D(); if (estimate) root.userData.speechPlacements = { generic: estimate }; return root }

test('a calibrated face wins over the estimate of the model', () => {
  assert.equal(speechFace(model(face(1)), speech({ face: face(0) }))?.meshIndex, 0)
})

test('speech without a face uses the humanoid estimate of the model', () => {
  assert.equal(speechFace(model(face(2)), speech({}))?.meshIndex, 2)
})

test('a face pack does not also paint the estimated head', () => {
  const pack = { workspaceId: 'cast', filename: 'pack.png', url: '/pack.png' }
  assert.equal(speechFace(model(face(2)), speech({ facePack: pack })), undefined)
  assert.equal(speechFace(model(face(1)), speech({ face: face(0), facePack: pack }))?.meshIndex, 0)
})

test('a model without an estimate or speech that is off has no face', () => {
  assert.equal(speechFace(model(), speech({})), undefined)
  assert.equal(speechFace(model(face(2)), speech({ enabled: false })), undefined)
  assert.equal(speechFace(model(face(2)), undefined), undefined)
})
