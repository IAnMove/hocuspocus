import assert from 'node:assert/strict'
import test from 'node:test'
import { catalogFromClips } from '../src/features/scene3d/gpu.ts'
import { footContactsInScene, parseFootContacts } from '../src/features/scene3d/performance.ts'
import type { Scene3DFootContact } from '../src/features/scene3d/types.ts'

const walk: Scene3DFootContact[] = [{ t: 0.4667, foot: 'right', strength: 0.26 }, { t: 0.9667, foot: 'left', strength: 0.26 }]
const times = (found: Array<{ sceneTime: number }>) => found.map(item => Number(item.sceneTime.toFixed(4)))

test('contacts from GLB extras keep only valid landings, in time order', () => {
  const parsed = parseFootContacts([
    { t: 0.9, foot: 'left', strength: 3 }, { t: 0.4, foot: 'right' }, { t: -1, foot: 'left' }, { t: 0.2, foot: 'paw' }, null, 'x',
  ])
  assert.deepEqual(parsed, [{ t: 0.4, foot: 'right', strength: 0.5 }, { t: 0.9, foot: 'left', strength: 1 }])
  assert.deepEqual(parseFootContacts(undefined), [])
})

test('the clip catalog carries contacts only when the animation records them', () => {
  const catalog = catalogFromClips([
    { name: 'Walk', duration: 1, userData: { hocuspocus_contacts: walk } },
    { name: 'Idle', duration: 2, userData: {} },
  ] as never)
  assert.deepEqual(catalog[0].contacts, walk)
  assert.equal('contacts' in catalog[1], false)
})

test('a looping clip repeats its landings over the scene', () => {
  assert.deepEqual(times(footContactsInScene(walk, 1, 2)), [0.4667, 0.9667, 1.4667, 1.9667])
  assert.deepEqual(footContactsInScene(walk, 1, 2).map(item => item.foot), ['right', 'left', 'right', 'left'])
})

test('speed 2 doubles the step rate', () => {
  const normal = footContactsInScene(walk, 1, 2)
  const fast = footContactsInScene(walk, 1, 2, { speed: 2 })
  assert.equal(fast.length, 2 * normal.length)
  assert.deepEqual(times(fast).slice(0, 2), [0.2333, 0.4833])
})

test('a start offset shifts landings and wraps them around the loop', () => {
  assert.deepEqual(times(footContactsInScene(walk, 1, 1, { start: 0.5 })), [0.4667, 0.9667])
  assert.deepEqual(footContactsInScene(walk, 1, 1, { start: 0.5 }).map(item => item.foot), ['left', 'right'])
})

test('a clip played once lands only while it plays and holds after its end', () => {
  assert.deepEqual(times(footContactsInScene(walk, 1, 5, { loop: false })), [0.4667, 0.9667])
  assert.deepEqual(times(footContactsInScene(walk, 1, 5, { loop: false, start: 0.6 })), [0.3667])
  assert.deepEqual(footContactsInScene(walk, null, 5), [])
  assert.deepEqual(footContactsInScene(walk, 1, 0), [])
})
