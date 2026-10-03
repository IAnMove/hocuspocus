import assert from 'node:assert/strict'
import test from 'node:test'
import { clipWeightsAt } from '../src/features/scene3d/clipCues.ts'
import { appendClipCue, removeClipCue, replaceClipCue, singleClipFromSequence, startClipSequence } from '../src/features/scene3d/clipSequenceEdit.ts'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import { patchScene3DSlot, remountScene3DTemplate } from '../src/features/scene3d/templates.ts'
import type { Scene3DSlot } from '../src/features/scene3d/types.ts'

const walk = { index: 0, name: 'Walk' }
const wave = { index: 1, name: 'Wave' }
const slot = { clip: walk, clipPlayback: { speed: 1.5, start: 0.4, loop: false } } as Pick<Scene3DSlot, 'clip' | 'clipPlayback'>

test('a sequence starts from the single clip and a zero fade is a cut', () => {
  const cues = startClipSequence(slot)
  assert.ok(cues)
  assert.equal(cues[0].fade, 0)
  assert.equal(cues[0].speed, 1.5)
  assert.equal(cues[0].offset, 0.4)
  assert.equal(cues[0].loop, false)
  const next = appendClipCue(cues, wave, 8)
  assert.equal(next?.[1].start, 2)
  assert.equal(next?.[1].fade, 0.3)
  assert.equal(next?.[1].clip.name, 'Wave')
  assert.deepEqual(clipWeightsAt(next!, 2, 8).map(item => item.cueIndex), [0, 1])
  assert.deepEqual(clipWeightsAt(replaceClipCue(next!, 1, { fade: 0 })!, 2, 8).map(item => item.weight), [1])
})

test('a bad edit keeps the cue, and leaving the sequence restores one clip', () => {
  const cues = appendClipCue(startClipSequence(slot)!, wave, 8)!
  const kept = replaceClipCue(cues, 1, { start: Number.NaN, fade: 12, duration: null })
  assert.equal(kept?.length, 2)
  assert.equal(kept?.[1].start, 2)
  assert.equal(kept?.[1].fade, 10)
  assert.equal(kept?.[1].duration, undefined)
  const one = singleClipFromSequence(removeClipCue(cues, 1)!)
  assert.equal(one.clips, undefined)
  assert.equal(one.clip?.name, 'Walk')
  assert.equal(one.clipPlayback.speed, 1.5)
  assert.equal(one.clipPlayback.start, 0.4)
  assert.equal(one.clipPlayback.loop, false)
})

test('the slot patch stores a sequence and a document without one stays on clip', () => {
  const document = createDefaultScene3DDocument()
  const model = document.slots.find(item => item.media === 'model3d')
  assert.ok(model)
  const cues = startClipSequence({ ...slot, clip: walk })!
  const patched = patchScene3DSlot(document, model.id, { clip: walk, clips: cues })
  assert.equal(patched.slots.find(item => item.id === model.id)?.clips?.[0].clip.name, 'Walk')
  const cleared = patchScene3DSlot(patched, model.id, singleClipFromSequence(cues))
  assert.equal(cleared.slots.find(item => item.id === model.id)?.clips, undefined)
  assert.equal(document.slots.find(item => item.id === model.id)?.clips, undefined)
})

test('changing the shot keeps a sequence, and a later single-clip write drops it', () => {
  const document = createDefaultScene3DDocument()
  const model = document.slots.find(item => item.media === 'model3d')
  assert.ok(model)
  const cues = appendClipCue(startClipSequence({ ...slot, clip: walk })!, wave, 8)!
  document.slots = document.slots.map(item => item.id === model.id
    ? { ...item, sourceUrl: '/api/v1/file/hero.glb?workspace=test', clip: walk, clips: cues }
    : item)
  const remounted = remountScene3DTemplate('duo-diagonal', document)
  const kept = remounted.slots.find(item => item.id === model.id)
  assert.equal(kept?.clips?.length, 2)
  assert.equal(kept?.clips?.[1].clip.name, 'Wave')
  assert.equal(kept?.clip?.name, 'Walk')
  const baked = patchScene3DSlot(remounted, model.id, {
    clip: { index: 4, name: 'Path Walk' },
    clipPlayback: { speed: 1, start: 0, loop: false },
    clips: undefined,
  })
  assert.equal(baked.slots.find(item => item.id === model.id)?.clips, undefined)
  assert.equal(baked.slots.find(item => item.id === model.id)?.clip?.name, 'Path Walk')
})
