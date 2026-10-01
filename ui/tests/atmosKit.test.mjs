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

test('composed pieces become one coloured geometry and a skyline stays behind the scene', async () => {
  const { composeGeometry, skylineLayers } = await import('../src/features/scene3d/atmos/sets/kit.ts')
  const geo = composeGeometry([
    { type: 'box', at: [0, 0.5, 0], size: [1, 1, 1], color: '#ff0000' },
    { type: 'sphere', at: [2, 0.5, 0], size: [1, 1, 1], color: '#00ff00' },
    { type: 'cone', at: [4, 0.5, 0], size: [1, 1, 1], turn: [0, 0.5, 0], color: '#0000ff' },
  ])
  const colors = geo.getAttribute('color')
  const position = geo.getAttribute('position')
  assert.equal(colors.count, position.count)
  assert.ok(position.count > 36 + 20, 'all three primitives are in the geometry')
  assert.equal(geo.getAttribute('uv'), undefined)
  assert.equal(geo.index, null, 'non-indexed, so every face keeps its own flat normal')
  const first = [colors.getX(0), colors.getY(0), colors.getZ(0)]
  const last = [colors.getX(colors.count - 1), colors.getY(colors.count - 1), colors.getZ(colors.count - 1)]
  assert.notDeepEqual(first, last)
  const a = skylineLayers(new Group(), kept(), { seed: 4, count: 6, radius: 20, height: [5, 9], width: [2, 3], body: '#202030', haze: '#605070', layers: 2 })
  const b = skylineLayers(new Group(), kept(), { seed: 4, count: 6, radius: 20, height: [5, 9], width: [2, 3], body: '#202030', haze: '#605070', layers: 2 })
  assert.deepEqual(places(a), places(b))
  assert.equal(a.count, 12)
  assert.ok(places(a).every(([, , z]) => z < -5), 'towers stay behind the roof')
})
