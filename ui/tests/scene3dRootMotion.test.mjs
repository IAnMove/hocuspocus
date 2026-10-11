import assert from 'node:assert/strict'
import test from 'node:test'
import { AnimationClip, Bone, Group, VectorKeyframeTrack } from 'three'
import { flattenRootMotion } from '../src/features/scene3d/rootMotion.ts'
import { bindMixer } from '../src/features/scene3d/gpu.ts'

function rig() {
  const root = new Group(); const hips = new Bone(); hips.name = 'Hips'; const leg = new Bone(); leg.name = 'Leg'
  hips.add(leg); root.add(hips)
  const travel = new VectorKeyframeTrack('Hips.position', [0, 1, 2], [0, 1, 0, 2, 1.5, 1, 4, 1, 2])
  const swing = new VectorKeyframeTrack('Leg.position', [0, 1, 2], [0, 0, 0, 0.5, 0, 0.25, 0, 0, 0])
  return { root, clip: new AnimationClip('dash', 2, [travel, swing]) }
}

test('a clip played on the spot keeps the root bob and the limbs but drops the travel across the floor', () => {
  const { root, clip } = rig()
  flattenRootMotion(root, clip)
  assert.deepEqual(Array.from(clip.tracks[0].values), [0, 1, 0, 0, 1.5, 0, 0, 1, 0])
  assert.deepEqual(Array.from(clip.tracks[1].values), [0, 0, 0, 0.5, 0, 0.25, 0, 0, 0])
  flattenRootMotion(root, clip)
  assert.deepEqual(Array.from(clip.tracks[0].values), [0, 1, 0, 0, 1.5, 0, 0, 1, 0], 'flattening twice changes nothing')
})

test('a slot marked in place binds its clip flattened; an ordinary slot keeps the travel', () => {
  const { root, clip } = rig()
  const slot = { id: 's', clip: { index: 0, name: 'dash' } }
  bindMixer(root, [clip], slot)
  assert.equal(clip.tracks[0].values[3], 2)
  bindMixer(root, [clip], { ...slot, inPlace: true })
  assert.equal(clip.tracks[0].values[3], 0)
})
