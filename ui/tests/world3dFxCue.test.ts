import assert from 'node:assert/strict'
import test from 'node:test'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { parseWorldSfx } from '../src/features/sceneFx/world.ts'

// The shapes services/world3d_world_fx.py writes for world3d.scene.patch's worldFx (tests/test_world3d_world_fx.py builds them).
const AT_A_POINT = { id: 'fx-explosion-1', kind: 'explosion', start: 1.5, end: 3.9, rotation: { x: 0, y: 0, z: 0 }, seed: 1234, position: { x: 2, y: 0.5, z: -3 },
  scale: 2, intensity: 1.4, color: '#ff6a32', sound: true, volume: 0.4 }
const ON_AN_OBJECT = { id: 'fx-sparks-1', kind: 'sparks', start: 2, end: 3.2, rotation: { x: 0, y: 0, z: 0 }, seed: 99, position: { x: 4.5, y: 1, z: -7 },
  anchor: { slotId: 'hero', offset: { x: 0, y: 0.15, z: 0.5 } } }
const A_BEAM = { id: 'fx-bolt', kind: 'lightning', start: 1, end: 1.8, rotation: { x: 0, y: 0, z: 0 }, seed: 5, position: { x: 1, y: 0, z: 0 },
  anchor: { slotId: 'a', offset: { x: 0, y: 0, z: 0 } }, target: { slotId: 'b', offset: { x: 0, y: 0, z: 0 } }, targetPosition: { x: 5, y: 0, z: 0 } }

test('the editor keeps every field of a world effect the agent patch writes', () => {
  const [point, onObject, beam] = parseWorldSfx([AT_A_POINT, ON_AN_OBJECT, A_BEAM])
  assert.deepEqual([point.id, point.kind, point.start, point.end, point.position, point.scale, point.intensity, point.color, point.sound, point.volume, point.seed],
    ['fx-explosion-1', 'explosion', 1.5, 3.9, { x: 2, y: 0.5, z: -3 }, 2, 1.4, '#ff6a32', true, 0.4, 1234])
  assert.deepEqual(onObject.anchor, { slotId: 'hero', offset: { x: 0, y: 0.15, z: 0.5 } })
  assert.equal(onObject.sound, false)
  assert.deepEqual(beam.target, { slotId: 'b', offset: { x: 0, y: 0, z: 0 } })
  assert.deepEqual(beam.targetPosition, { x: 5, y: 0, z: 0 })
})

test('a document with those cues opens, and a cue the editor cannot keep is dropped, not the document', () => {
  const doc = createDefaultScene3DDocument()
  const parsed = parseScene3DDocument(JSON.parse(JSON.stringify({ ...doc, worldSfx: [AT_A_POINT, { ...ON_AN_OBJECT, id: AT_A_POINT.id }, { ...A_BEAM, end: 0.5 }, { ...A_BEAM, kind: 'teapot', id: 'fx-odd' }] })))
  assert.ok(parsed)
  assert.deepEqual(parsed!.worldSfx?.map(cue => cue.id), ['fx-explosion-1'], 'a repeated id, an end before the start and an unknown kind are dropped')
})
