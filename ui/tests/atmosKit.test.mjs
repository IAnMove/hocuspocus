import assert from 'node:assert/strict'
import test from 'node:test'
import { Group, Matrix4 } from 'three'
import { boulders, paintedTerrain, ridge } from '../src/features/scene3d/atmos/sets/kit.ts'

function kept() { return { geometries: [], materials: [], textures: [] } }
function places(mesh) {
  const m = new Matrix4()
  return Array.from({ length: mesh.count }, (_, i) => { mesh.getMatrixAt(i, m); return [m.elements[12], m.elements[13], m.elements[14]] })
}

test('painted terrain keeps its flat disc flat and tracks what it must dispose', () => {
  const root = new Group()
  const k = kept()
  const mesh = paintedTerrain(root, k, {
    size: 20, segments: 40, seed: 3, paint: { base: '#887766', alt: '#aa9988', fleck: '#ffffff', seed: 3 },
    height: () => 1, flat: { x: 0, z: 0, radius: 2 },
  })
  const pos = mesh.geometry.getAttribute('position')
  let centre = Infinity
  let far = -Infinity
  for (let i = 0; i < pos.count; i += 1) {
    const d = Math.hypot(pos.getX(i), pos.getZ(i))
    if (d < 1.9) centre = Math.min(centre, Math.abs(pos.getY(i)))
    if (d > 6) far = Math.max(far, pos.getY(i))
  }
  assert.ok(centre < 1e-9, 'the character spot is flat')
  assert.ok(far > 0.99, 'the rest follows the height function')
  assert.equal(mesh.name, 'atmos-ground')
  assert.ok(mesh.geometry.getAttribute('color'))
  assert.ok(k.geometries.length >= 1 && k.materials.length >= 1)
  assert.ok(k.textures.length === 1 || typeof document === 'undefined')
})

test('boulders and ridges are deterministic and sit where they are told', () => {
  const spots = [{ x: 1, z: -2, size: 0.5 }, { x: -3, z: -4, size: 0.3, flat: 0.5 }]
  const a = boulders(new Group(), kept(), spots, ['#888888', '#aaaaaa'], 7)
  const b = boulders(new Group(), kept(), spots, ['#888888', '#aaaaaa'], 7)
  assert.deepEqual(places(a), places(b))
  assert.equal(a.count, 2)
  assert.ok(places(a).every(([, y]) => y > 0), 'boulders rest on the ground, not in it')
  const r1 = ridge(new Group(), kept(), { seed: 5, count: 6, radius: 15, height: [2, 4], width: [3, 5], color: '#445566', haze: '#aabbcc', layers: 2 })
  const r2 = ridge(new Group(), kept(), { seed: 5, count: 6, radius: 15, height: [2, 4], width: [3, 5], color: '#445566', haze: '#aabbcc', layers: 2 })
  assert.deepEqual(places(r1), places(r2))
  assert.equal(r1.count, 12)
  assert.ok(places(r1).every(([, , z]) => z < 0), 'ridges stay behind the scene')
})
