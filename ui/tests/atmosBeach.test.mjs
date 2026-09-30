import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildBeach } from '../src/features/scene3d/atmos/sets/beach.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'amber', timeOfDay: 'golden', variant: 5, ...patch }, 'atmos-beach'), quality, 'atmos-beach')
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

test('beach templates keep amber, golden hour, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-beach-wide')
  const low = atmosTemplateDocument('atmos-beach-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-beach')
    assert.equal(doc.atmos?.timeOfDay, 'golden')
    assert.equal(doc.atmos?.palette, 'amber')
    assert.equal(doc.atmos?.variant, 5)
    assert.deepEqual([...doc.light.direction], [-0.55, -0.22, -0.72])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
  }
  assert.deepEqual([...wide.camera.eye], [0.15, 1.5, 4.35])
  assert.equal(wide.camera.fov, 48)
  assert.deepEqual([...low.camera.eye], [1.15, 0.72, 2.85])
  assert.equal(low.camera.fov, 54)
  assert.equal(settingFromDressing('atmos-beach'), 'sea')
  assert.equal(parseAtmosSettings({ palette: 'amber', timeOfDay: 'dusk', variant: 20 }, 'atmos-beach')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'coral', variant: -1 }, 'atmos-beach')?.variant, 0)
})

test('rocks, palms, the boat and the gulls stay off the lane', () => {
  const first = buildBeach(resolved(), true)
  const again = buildBeach(resolved(), true)
  const rocks = places(first.root.getObjectByName('atmos-rock'))
  assert.deepEqual(rocks, places(again.root.getObjectByName('atmos-rock')))
  assert.ok(rocks.length >= 5)
  for (const name of ['atmos-rock', 'atmos-palm', 'atmos-trunk', 'atmos-boat', 'atmos-gull']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  const water = first.root.getObjectByName('atmos-water')
  assert.equal(outsideLane(water.position.x, water.position.z), true)
  assert.ok(water.position.z < -2.4)
  const normal = water.geometry.getAttribute('normal')
  let facing = 0
  for (let i = 0; i < normal.count; i += 1) if (normal.getY(i) > 0.5) facing += 1
  assert.equal(facing, normal.count)
  const ground = first.root.getObjectByName('atmos-ground')
  assert.equal(ground.material.uniforms.uSand.value.getHexString(), 'e6c07a')
  assert.equal(water.material.uniforms.uAmp.value, 5)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('the tide advances and dusk keeps the shore', () => {
  const built = buildBeach(resolved(), true)
  const water = built.root.getObjectByName('atmos-water')
  const gulls = built.root.getObjectByName('atmos-gull')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const parked = places(gulls)[0][0]
  built.handle.sync(2, {}, {}, 'low', 3, resolved({ variant: 8 }))
  assert.ok(water.material.uniforms.uTime.value > 1)
  assert.equal(water.material.uniforms.uAmp.value, 8)
  assert.notEqual(places(gulls)[0][0], parked)
  const calm = buildBeach(resolved({ variant: 0 }), true)
  assert.equal(calm.root.getObjectByName('atmos-water').material.uniforms.uAmp.value, 0)
  assert.ok(calm.root.getObjectByName('atmos-boat'))
  const dusk = buildBeach(resolved({ timeOfDay: 'dusk', palette: 'coral' }, 'high'), true)
  assert.equal(dusk.root.getObjectByName('atmos-palm').count, 6)
  assert.ok(dusk.root.getObjectByName('atmos-sun').position.y < 1.6)
  built.handle.dispose()
  built.handle.dispose()
  calm.handle.dispose()
  dusk.handle.dispose()
})

test('beach degrades to a flat sand field without WebGL2', () => {
  const flat = buildBeach(resolved(), false)
  assert.equal(flat.root.getObjectByName('atmos-palm'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-water'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-boat'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-beach-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [255, 196, 154])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
