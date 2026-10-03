import assert from 'node:assert/strict'
import test from 'node:test'
import { AnimationClip, Object3D, Quaternion, QuaternionKeyframeTrack, Vector3 } from 'three'
import { clipWeightsAt, cueContactsInScene, cueLocalTime, parseClipCues, type Scene3DClipCue } from '../src/features/scene3d/clipCues.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { paintClipCues } from '../src/features/scene3d/gpu.ts'

const walk = { index: 0, name: 'Walk' }
const wave = { index: 1, name: 'Wave' }
const length = (clip: { index: number }) => (clip.index === 0 ? 1 : 2)
const sum = (items: { weight: number }[]) => items.reduce((total, item) => total + item.weight, 0)

test('a cut with no fade switches at the cue start; weights always sum to one', () => {
  const cues: Scene3DClipCue[] = [{ clip: walk, start: 0 }, { clip: wave, start: 2, fade: 0 }]
  assert.deepEqual(clipWeightsAt(cues, 1.999, 4, length).map(item => item.cueIndex), [0])
  assert.deepEqual(clipWeightsAt(cues, 2, 4, length), [{ cueIndex: 1, weight: 1, localTime: 0 }])
  for (const t of [0, 0.5, 1.9, 2, 3.3, 4]) assert.ok(Math.abs(sum(clipWeightsAt(cues, t, 4, length)) - 1) < 1e-12)
})

test('the next cue fades in smoothly over its own first fade seconds', () => {
  const cues: Scene3DClipCue[] = [{ clip: walk, start: 0 }, { clip: wave, start: 2, fade: 0.4 }]
  const at = (t: number) => clipWeightsAt(cues, t, 4, length)
  assert.deepEqual(at(2).map(item => [item.cueIndex, item.weight]), [[0, 1], [1, 0]])
  const middle = at(2.2)
  assert.ok(middle.every(item => Math.abs(item.weight - 0.5) < 1e-9), 'half way through the fade')
  assert.ok(Math.abs(at(2.1)[1].weight + at(2.3)[1].weight - 1) < 1e-12, 'smoothstep is symmetric about the middle')
  assert.ok(Math.abs(middle[0].localTime - 0.2) < 1e-9, 'the outgoing cue keeps playing through the fade (looped walk)')
  assert.deepEqual(at(2.4).map(item => [item.cueIndex, item.weight]), [[1, 1]])
  assert.ok(Math.abs(at(2.4)[0].localTime - 0.4) < 1e-9)
  assert.ok(Math.abs(sum(at(2.27)) - 1) < 1e-12)
})

test('before the first cue it holds its start; speed, offset, loop and duration shape the clip time', () => {
  const cues: Scene3DClipCue[] = [{ clip: wave, start: 1, offset: 0.5, speed: 2 }]
  assert.deepEqual(clipWeightsAt(cues, 0.3, 4, length), [{ cueIndex: 0, weight: 1, localTime: 0.5 }])
  assert.equal(cueLocalTime(cues[0], 1.5, 2), 1.5)
  assert.equal(cueLocalTime(cues[0], 2.5, 2), 1.5, 'looped: 0.5 + 3 wraps to 1.5')
  assert.equal(cueLocalTime({ ...cues[0], loop: false }, 2.5, 2), 2, 'clamped at the clip end')
  assert.equal(cueLocalTime({ ...cues[0], duration: 0.25 }, 3, 2), 1, 'the clock stops at the cue duration')
  assert.deepEqual(clipWeightsAt(cues, 9, 4, length), clipWeightsAt(cues, 4, 4, length), 'after the shot end it holds the last frame')
})

test('the same time always gives the same answer, in any order', () => {
  const cues: Scene3DClipCue[] = [{ clip: walk, start: 0 }, { clip: wave, start: 1.5, fade: 0.5 }, { clip: walk, start: 3, fade: 0.2 }]
  const times = [3.1, 0.2, 1.7, 3.1, 0.2, 1.7]
  const first = times.map(t => JSON.stringify(clipWeightsAt(cues, t, 4, length)))
  const again = [...times].reverse().map(t => JSON.stringify(clipWeightsAt(cues, t, 4, length))).reverse()
  assert.deepEqual(first, again)
})

test('a stored sequence is bounded, sorted and survives a reload; without clips nothing is added', () => {
  const parsed = parseClipCues([
    { clip: wave, start: 2, fade: 99, speed: 9 }, { clip: walk, start: 0 }, { clip: { index: -1, name: 'x' }, start: 1 },
    { clip: walk, start: 'soon' }, ...Array.from({ length: 40 }, (_v, i) => ({ clip: walk, start: 10 + i })),
  ])!
  assert.equal(parsed.length, 32)
  assert.deepEqual(parsed.slice(0, 2), [{ clip: walk, start: 0 }, { clip: wave, start: 2, fade: 10, speed: 4 }])
  assert.equal(parseClipCues([]), undefined)
  const doc = createDefaultScene3DDocument()
  doc.slots[0] = { ...doc.slots[0], clips: [{ clip: walk, start: 0 }, { clip: wave, start: 2, fade: 0.4 }] }
  assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(doc)))!.slots[0].clips, doc.slots[0].clips)
  const plain = parseScene3DDocument(JSON.parse(JSON.stringify(createDefaultScene3DDocument())))!
  assert.equal('clips' in plain.slots[0], false)
})

test('foot landings follow each cue clock and only count while the cue weighs half or more', () => {
  const cues: Scene3DClipCue[] = [{ clip: walk, start: 0 }, { clip: wave, start: 2, fade: 0.4 }]
  const catalog = (clip: { index: number }) => clip.index === 0
    ? { durationSeconds: 1, contacts: [{ t: 0.25, foot: 'left' as const, strength: 0.4 }, { t: 0.75, foot: 'right' as const, strength: 0.4 }] }
    : { durationSeconds: 2, contacts: [] }
  const landings = cueContactsInScene(cues, catalog, 4)
  assert.deepEqual(landings.map(item => item.sceneTime), [0.25, 0.75, 1.25, 1.75])
  assert.ok(landings.every(item => item.cueIndex === 0))
  const fast = cueContactsInScene([{ clip: walk, start: 0, speed: 2 }], catalog, 1)
  assert.deepEqual(fast.map(item => item.sceneTime), [0.125, 0.375, 0.625, 0.875])
  const once = cueContactsInScene([{ clip: walk, start: 1, loop: false, offset: 0.5 }], catalog, 4)
  assert.deepEqual(once.map(item => [item.sceneTime, item.foot]), [[1.25, 'right']])
})

function turnTrack(name: string, degrees: number) {
  const q = new Quaternion().setFromAxisAngle(new Vector3(0, 1, 0), (degrees * Math.PI) / 180)
  return new AnimationClip(name, 1, [new QuaternionKeyframeTrack('bone.quaternion', [0, 1], [...q.toArray(), ...q.toArray()])])
}

test('the mixer shows the blend half way through a fade and each clip alone outside it', () => {
  const root = new Object3D(), bone = new Object3D()
  bone.name = 'bone'; root.add(bone)
  const gpu: Parameters<typeof paintClipCues>[0] = { root, animations: [turnTrack('Walk', 0), turnTrack('Wave', 90)], cues: undefined }
  const cues: Scene3DClipCue[] = [{ clip: walk, start: 0 }, { clip: wave, start: 2, fade: 0.4 }]
  const yaw = () => (new Vector3(0, 0, 1).applyQuaternion(bone.quaternion).angleTo(new Vector3(0, 0, 1)) * 180) / Math.PI
  paintClipCues(gpu, cues, 1, 4)
  assert.ok(yaw() < 1e-4)
  paintClipCues(gpu, cues, 2.2, 4)
  assert.ok(Math.abs(yaw() - 45) < 1e-3, `mid-fade yaw ${yaw()}`)
  paintClipCues(gpu, cues, 3, 4)
  assert.ok(Math.abs(yaw() - 90) < 1e-3)
  paintClipCues(gpu, cues, 1, 4)
  assert.ok(yaw() < 1e-4, 'seeking back gives the same pose: nothing accumulates')
  const mixer = gpu.cues!.mixer
  paintClipCues(gpu, cues, 2.2, 4)
  assert.equal(gpu.cues!.mixer, mixer, 'the mixer is rebuilt only when the clips change')
})
