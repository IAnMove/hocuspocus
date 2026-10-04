import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildDesert } from '../src/features/scene3d/atmos/sets/desert.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'sand', timeOfDay: 'noon', variant: 5, ...patch }, 'atmos-desert'), quality, 'atmos-desert')
}

function places(mesh) {
  const matrix = new Matrix4()
  const spots = []
  for (let i = 0; i < mesh.count; i += 1) {
    mesh.getMatrixAt(i, matrix)
    spots.push([matrix.elements[12], matrix.elements[13], matrix.elements[14]])
  }
  return spots
}

function outsideLane(x, z) {
  const dx = x - CLEARING_SUBJECT[0]
  const dz = z - CLEARING_SUBJECT[2]
  const inCircle = dx * dx + dz * dz < 1.4 * 1.4
  const inLane = z > -1.15 && z < 3.5 && x > -1.05 && x < 1.7
  return !inCircle && !inLane
}

test('desert templates keep sand, noon, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-desert-wide')
  const low = atmosTemplateDocument('atmos-desert-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-desert')
    assert.equal(doc.atmos?.timeOfDay, 'noon')
    assert.equal(doc.atmos?.palette, 'sand')
    assert.equal(doc.atmos?.variant, 5)
    assert.deepEqual([...doc.light.direction], [0.15, -0.82, -0.42])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
  }
  assert.deepEqual([...wide.camera.eye], [0.08, 1.62, 4.25])
  assert.equal(wide.camera.fov, 48)
  assert.deepEqual([...low.camera.eye], [0.35, 0.9, 2.7])
  assert.equal(low.camera.fov, 54)
  assert.equal(settingFromDressing('atmos-desert'), 'desert')
  assert.equal(parseAtmosSettings({ palette: 'sand', timeOfDay: 'dusk', variant: 20 }, 'atmos-desert')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'gold', variant: -1 }, 'atmos-desert')?.variant, 0)
})

test('dunes, palms, the pool and the ruins stay off the lane', () => {
  const first = buildDesert(resolved(), true)
  const again = buildDesert(resolved(), true)
  const dunes = places(first.root.getObjectByName('atmos-dune'))
  assert.deepEqual(dunes, places(again.root.getObjectByName('atmos-dune')))
  assert.ok(dunes.length >= 6)
  for (const name of ['atmos-dune', 'atmos-palm', 'atmos-trunk', 'atmos-ruin']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  const pool = first.root.getObjectByName('atmos-pool')
  assert.equal(outsideLane(pool.position.x, pool.position.z), true)
  const normal = pool.geometry.getAttribute('normal')
  let facing = 0
  for (let i = 0; i < normal.count; i += 1) if (normal.getY(i) > 0.5) facing += 1
  assert.equal(facing, normal.count)
  for (const [x, , z] of places(first.root.getObjectByName('atmos-palm'))) {
    const dx = x - pool.position.x
    const dz = z - pool.position.z
    assert.ok(dx * dx + dz * dz > 2.4 * 2.4)
  }
  const ground = first.root.getObjectByName('atmos-ground')
  assert.equal(ground.material.uniforms.uAmp.value, 5)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('wind ripples advance and dusk keeps the oasis', () => {
  const built = buildDesert(resolved(), true)
  const ground = built.root.getObjectByName('atmos-ground')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  built.handle.sync(2, {}, {}, 'low', 3, resolved({ variant: 8 }))
  assert.ok(ground.material.uniforms.uTime.value > 1)
  assert.equal(ground.material.uniforms.uAmp.value, 8)
  const calm = buildDesert(resolved({ variant: 0 }), true)
  assert.equal(calm.root.getObjectByName('atmos-ground').material.uniforms.uAmp.value, 0)
  assert.ok(calm.root.getObjectByName('atmos-pool'))
  const dusk = buildDesert(resolved({ timeOfDay: 'dusk', palette: 'gold' }, 'high'), true)
  assert.equal(dusk.root.getObjectByName('atmos-palm').count, 10)
  built.handle.dispose()
  built.handle.dispose()
  calm.handle.dispose()
  dusk.handle.dispose()
})

test('desert degrades to a flat sand field without WebGL2', () => {
  const flat = buildDesert(resolved(), false)
  assert.equal(flat.root.getObjectByName('atmos-palm'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-pool'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-desert-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [242, 215, 164])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
