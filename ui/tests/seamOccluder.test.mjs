import assert from 'node:assert/strict'
import test from 'node:test'
import { createNarrativeScene } from '../src/lib/sceneNarrative.ts'
import { normalizeSeamOccluder, seamOccluderPhase, suggestSeamOccluderKind } from '../src/lib/seamOccluder.ts'

test('station-like plates pick a lamp; forests pick a tree; default is a pole', () => {
  assert.equal(suggestSeamOccluderKind('Train station platform at night'), 'lamp')
  assert.equal(suggestSeamOccluderKind('Dense pine forest'), 'tree')
  assert.equal(suggestSeamOccluderKind('Ancient temple hall'), 'column')
  assert.equal(suggestSeamOccluderKind('Open sky'), 'pole')
})

test('occluders sit on the tile join, half a spacing ahead of the plate', () => {
  assert.equal(seamOccluderPhase({ phase: 0, spacing: 100 }), 50)
  assert.equal(seamOccluderPhase({ phase: 12, spacing: 80 }), 52)
})

test('seam cover presentation is bounded so a bad recipe cannot create an opaque card', () => {
  assert.deepEqual(normalizeSeamOccluder({ enabled: true, kind: 'tree', scale: 9, opacity: -4 }), {
    enabled: true, kind: 'tree', scale: 1.8, opacity: .2,
  })
  assert.deepEqual(normalizeSeamOccluder({ enabled: true, kind: 'lamp', scale: .7, opacity: .65 }), {
    enabled: true, kind: 'lamp', scale: .7, opacity: .65,
  })
})

test('run-travel parallax enables a seam cover locked to the background strip', () => {
  const scene = createNarrativeScene('run-travel-parallax', {
    hero: { source: '/hero.glb', type: 'model3d', name: 'Runner' },
    plate: { source: '/station.jpg', type: 'image', name: 'Train station' },
  })
  const plate = scene.layers.find(layer => layer.id === 'plate')
  assert.equal(plate?.strip?.enabled, true)
  assert.equal(plate?.strip?.seamOccluder?.enabled, true)
  assert.equal(plate?.strip?.seamOccluder?.kind, 'lamp')
  assert.equal(seamOccluderPhase(plate.strip), (plate.strip?.phase ?? 0) + (plate.strip?.spacing ?? 0) / 2)
})
