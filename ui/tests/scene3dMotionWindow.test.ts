import assert from 'node:assert/strict'
import { readFileSync, writeFileSync } from 'node:fs'
import test from 'node:test'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { motionWindow, parseMotion, slotPoseAtTime } from '../src/features/scene3d/performance.ts'
import { isTimedMove, isWalkBaked, walkKey } from '../src/features/scene3d/walkPath.ts'
import type { Scene3DMotion, Scene3DSlot, Vec3 } from '../src/features/scene3d/types.ts'

// The same cases and numbers tests/test_world3d_scene_motion.py checks the Python port against (services/world3d_scene_motion.py).
const FIXTURE = new URL('../../tests/fixtures/world3d_motion_samples.json', import.meta.url)
const TIMES = [0, 0.4, 1, 1.5, 2, 2.6, 3, 3.5, 4, 5]
const DURATION = 4

type Case = { name: string; position: Vec3; rotationY: number; motion: Scene3DMotion }
const CASES: Case[] = [
  { name: 'straight, linear, whole shot', position: [0, 0, 0], rotationY: 0.3, motion: { to: [4, 0, 8] } },
  { name: 'straight, smooth, face travel', position: [1, 0.5, -2], rotationY: 0, motion: { to: [-5, 2, 6], easing: 'smooth', faceTravel: true } },
  { name: 'via curve, smooth, heading offset', position: [-3, 1, 0], rotationY: 0, motion: { to: [3, 1, 0], via: [0, 4, -3], easing: 'smooth', faceTravel: true, headingOffset: 1.5707963267948966 } },
  { name: 'waypoints, linear, face travel', position: [0, 0, 0], rotationY: 0, motion: { to: [6, 2, 6], points: [[2, 0, 4], [4, 1, 1]], faceTravel: true } },
  { name: 'turn to, smooth', position: [2, 0, 2], rotationY: 0.5, motion: { to: [2, 0, -6], turnTo: 3, easing: 'smooth' } },
  { name: 'window 1 to 3, straight, face travel', position: [0, 0, 8], rotationY: 0, motion: { to: [1, 0, -4], start: 1, end: 3, faceTravel: true } },
  { name: 'window 1 to 3, smooth, via', position: [-2, 1, 0], rotationY: 0, motion: { to: [2, 3, 0], via: [0, 5, 2], start: 1, end: 3, easing: 'smooth' } },
  { name: 'start only (2 s), smooth', position: [0, 0, 0], rotationY: 0, motion: { to: [0, 0, 5], start: 2, easing: 'smooth', faceTravel: true } },
  { name: 'end only (1.5 s), linear', position: [0, 0, 0], rotationY: 0, motion: { to: [3, 0, 0], end: 1.5 } },
  { name: 'window 0.5 to 3.5, waypoints, smooth', position: [0, 0, 0], rotationY: 0, motion: { to: [6, 2, 6], points: [[2, 0, 4], [4, 1, 1]], start: 0.5, end: 3.5, easing: 'smooth', faceTravel: true } },
]

function slotOf(item: Case): Scene3DSlot {
  return { ...createDefaultScene3DDocument().slots[0], position: item.position, rotationY: item.rotationY, motion: item.motion }
}

const round = (value: number) => Math.round(value * 1e9) / 1e9

function sampled() {
  return CASES.map(item => ({
    ...item,
    samples: TIMES.map(seconds => {
      const pose = slotPoseAtTime(slotOf(item), seconds, DURATION)
      return { t: seconds, position: pose.position.map(round), rotationY: round(pose.rotationY) }
    }),
  }))
}

test('the pose samples the Python port is checked against are what the runtime computes', () => {
  const now = `{"duration":${DURATION},"cases":[\n${sampled().map(item => JSON.stringify(item)).join(',\n')}\n]}\n`
  if (process.env.UPDATE_MOTION_SAMPLES === '1') writeFileSync(FIXTURE, now)
  assert.deepEqual(JSON.parse(readFileSync(FIXTURE, 'utf8')), JSON.parse(now), 'regenerate with UPDATE_MOTION_SAMPLES=1 only when the runtime formulas change on purpose')
})

test('a move without start and end runs over the whole shot exactly as before', () => {
  const reference = (slot: Scene3DSlot, seconds: number) => {
    const motion = slot.motion!
    const progress = Math.max(0, Math.min(1, seconds / Math.max(0.001, DURATION)))
    const t = motion.easing === 'smooth' ? progress * progress * (3 - 2 * progress) : progress
    return slot.position.map((v, i) => v + (motion.to[i] - v) * t)
  }
  for (const item of CASES.filter(entry => !entry.motion.via && !entry.motion.points && entry.motion.start === undefined && entry.motion.end === undefined)) {
    for (const seconds of TIMES) assert.deepEqual(slotPoseAtTime(slotOf(item), seconds, DURATION).position, reference(slotOf(item), seconds), `${item.name} at ${seconds}`)
  }
  assert.deepEqual(motionWindow({}, DURATION), { start: 0, end: DURATION })
})

test('before start the object sits at its slot position, between it moves, after end it stays at the destination', () => {
  const slot = slotOf(CASES[5])
  assert.deepEqual(slotPoseAtTime(slot, 0, DURATION).position, [0, 0, 8])
  assert.deepEqual(slotPoseAtTime(slot, 1, DURATION).position, [0, 0, 8])
  assert.deepEqual(slotPoseAtTime(slot, 2, DURATION).position, [0.5, 0, 2])
  assert.deepEqual(slotPoseAtTime(slot, 3, DURATION).position, [1, 0, -4])
  assert.deepEqual(slotPoseAtTime(slot, 4, DURATION).position, [1, 0, -4])
  assert.deepEqual(motionWindow(slot.motion!, DURATION), { start: 1, end: 3 })
})

test('an invalid window is dropped whole and the move runs over the shot; a valid one survives the document', () => {
  const to = [1, 0, 0]
  assert.deepEqual(parseMotion({ to, start: 1, end: 3 })?.start, 1)
  assert.equal(parseMotion({ to, start: 1 })?.end, undefined)
  for (const bad of [{ start: 3, end: 1 }, { start: 2, end: 2 }, { start: -1 }, { end: Number.NaN }, { start: '1' }, { end: 601 }]) {
    const parsed = parseMotion({ to, ...bad })!
    assert.equal(parsed.start, undefined, JSON.stringify(bad))
    assert.equal(parsed.end, undefined, JSON.stringify(bad))
  }
  assert.equal('start' in parseMotion({ to })!, false, 'a document without a window gains no keys')
  const doc = createDefaultScene3DDocument()
  doc.slots[0].motion = { to: [1, 0, 0], start: 1, end: 2.5, easing: 'smooth' }
  doc.slots[0].collide = false
  const again = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))!.slots[0]
  assert.equal(again.motion?.start, 1)
  assert.equal(again.motion?.end, 2.5)
  assert.equal(again.collide, false)
  doc.slots[0].collide = true as unknown as false
  assert.equal('collide' in parseScene3DDocument(JSON.parse(JSON.stringify(doc)))!.slots[0], false, 'collide is only ever false')
})

test('a baked walk knows nothing of a window: a timed move is stale and keeps its old key when untimed', () => {
  const slot: Scene3DSlot = { ...createDefaultScene3DDocument().slots[0], position: [0, 0, 0], sourceUrl: '/api/v1/file/hero.glb?workspace=w', clip: { index: 4, name: 'Path Walk' },
    motion: { to: [0, 0, 4], faceTravel: true } }
  const untimed = walkKey(slot, 4)
  assert.equal(untimed, JSON.stringify([[0, 0, 0], slot.rotationY, slot.scale, [0, 0, 4], null, null, 4]))
  slot.motion!.walk = { sourceUrl: slot.sourceUrl, clip: { index: 4, name: 'Path Walk' }, key: untimed }
  assert.equal(isWalkBaked(slot, 4), true)
  const timed = { ...slot, motion: { ...slot.motion!, start: 1 } }
  assert.equal(isTimedMove(timed.motion), true)
  assert.equal(isWalkBaked(timed, 4), false)
  assert.notEqual(walkKey(timed, 4), untimed)
  assert.equal(isTimedMove(slot.motion), false)
})
