import assert from 'node:assert/strict'
import test from 'node:test'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { slotPoseAtTime } from '../src/features/scene3d/performance.ts'
import { isWalkBaked, motionPathPoints, toModelSpace, walkKey } from '../src/features/scene3d/walkPath.ts'
import type { Scene3DSlot } from '../src/features/scene3d/types.ts'

function walker(): Scene3DSlot {
  const slot = createDefaultScene3DDocument().slots[0]
  return { ...slot, position: [0, 0, 0], sourceUrl: '/api/v1/file/hero.glb?workspace=w', clip: { index: 4, name: 'Path Walk' },
    motion: { to: [0, 0, 4], faceTravel: true, easing: 'linear' } }
}

test('a matching bake keeps the slot at its start; the clip moves the model', () => {
  const slot = walker()
  slot.motion!.walk = { sourceUrl: slot.sourceUrl, clip: { index: 4, name: 'Path Walk' }, key: walkKey(slot, 4) }
  assert.equal(isWalkBaked(slot, 4), true)
  assert.deepEqual(slotPoseAtTime(slot, 2, 4), { position: [0, 0, 0], rotationY: slot.rotationY })
})

test('editing the path, the placement or the clip makes the bake stale and the slot slides again', () => {
  const base = walker()
  base.motion!.walk = { sourceUrl: base.sourceUrl, clip: { index: 4, name: 'Path Walk' }, key: walkKey(base, 4) }
  const moved = { ...base, motion: { ...base.motion!, to: [0, 0, 5] as [number, number, number] } }
  assert.equal(isWalkBaked(moved, 4), false)
  assert.deepEqual(slotPoseAtTime(moved, 2, 4).position, [0, 0, 2.5])
  assert.equal(isWalkBaked({ ...base, rotationY: 1 }, 4), false)
  assert.equal(isWalkBaked({ ...base, clip: { index: 0, name: 'Idle' } }, 4), false)
  assert.equal(isWalkBaked(base, 6), false, 'a different shot length needs a new bake')
})

test('waypoints are walked on a curve through every point', () => {
  const slot = walker()
  slot.motion = { to: [4, 0, 4], points: [[0, 0, 4]], faceTravel: true, easing: 'linear' }
  assert.deepEqual(slotPoseAtTime(slot, 0, 4).position.map(v => Math.round(v * 1000) / 1000), [0, 0, 0])
  assert.deepEqual(slotPoseAtTime(slot, 4, 4).position.map(v => Math.round(v * 1000) / 1000), [4, 0, 4])
  const middle = slotPoseAtTime(slot, 2, 4).position
  assert.ok(Math.hypot(middle[0] - 0, middle[2] - 4) < 0.6, `near the waypoint: ${middle}`)
  assert.deepEqual(motionPathPoints(slot), [[0, 0, 0], [0, 0, 4], [4, 0, 4]])
})

test('a curve through via is sampled for the bake, start to end', () => {
  const slot = walker()
  slot.motion = { to: [0, 0, 4], via: [2, 0, 2], faceTravel: true }
  const points = motionPathPoints(slot)
  assert.equal(points.length, 9)
  assert.deepEqual(points[0], [0, 0, 0]); assert.deepEqual(points[8], [0, 0, 4])
  assert.deepEqual(points[4], [1, 0, 2])
})

test('scene points go to model space by undoing position, turn and fit scale', () => {
  const placement = { position: [1, 0, 1] as [number, number, number], rotationY: Math.PI / 2, scale: 2 }
  const [[x, z]] = toModelSpace([[1, 0, 3]], placement)
  // Two metres along +z in the scene, a quarter turn, half scale: one model unit along -x.
  assert.ok(Math.abs(x + 1) < 1e-9 && Math.abs(z) < 1e-9, `${x}, ${z}`)
})

test('waypoints and the bake survive a save and reload', () => {
  const doc = createDefaultScene3DDocument()
  const slot = walker()
  slot.motion = { to: [4, 0, 4], points: [[0, 0, 4]], faceTravel: true, easing: 'linear', walk: { sourceUrl: slot.sourceUrl, clip: { index: 4, name: 'Path Walk' }, key: 'k' } }
  doc.slots = [slot]
  const parsed = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))!
  assert.deepEqual(parsed.slots[0].motion?.points, [[0, 0, 4]])
  assert.deepEqual(parsed.slots[0].motion?.walk, slot.motion.walk)
  const broken = JSON.parse(JSON.stringify(doc))
  broken.slots[0].motion.points = [[0, 'x', 4]]
  broken.slots[0].motion.walk = { sourceUrl: '', clip: { index: -1, name: 'x' }, key: 'k' }
  const cleaned = parseScene3DDocument(broken)!
  assert.equal(cleaned.slots[0].motion?.points, undefined)
  assert.equal(cleaned.slots[0].motion?.walk, undefined)
})
