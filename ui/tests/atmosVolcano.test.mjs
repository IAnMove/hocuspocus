import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildVolcano } from '../src/features/scene3d/atmos/sets/volcano.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'magma', timeOfDay: 'erupt', variant: 5, ...patch }, 'atmos-volcano'), quality, 'atmos-volcano')
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

test('volcano templates keep magma, an eruption, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-volcano-wide')
  const low = atmosTemplateDocument('atmos-volcano-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-volcano')
    assert.equal(doc.atmos?.timeOfDay, 'erupt')
    assert.equal(doc.atmos?.palette, 'magma')
    assert.equal(doc.atmos?.variant, 5)
    assert.deepEqual([...doc.light.direction], [0.2, -0.78, -0.42])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.12, 1.7, 4.8])
  assert.equal(wide.camera.fov, 52)
  assert.deepEqual([...low.camera.eye], [0.9, 1.05, 2.55])
  assert.equal(low.camera.fov, 56)
  assert.equal(settingFromDressing('atmos-volcano'), 'volcano')
  assert.equal(parseAtmosSettings({ palette: 'magma', timeOfDay: 'calm', variant: 20 }, 'atmos-volcano')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'ash', variant: -1 }, 'atmos-volcano')?.variant, 0)
  assert.equal(parseAtmosSettings({ timeOfDay: 'noon' }, 'atmos-volcano')?.timeOfDay, 'erupt')
})

test('cones, rocks, vents and ash stay off the lane', () => {
  const first = buildVolcano(resolved(), true)
  const again = buildVolcano(resolved(), true)
  const rocks = places(first.root.getObjectByName('atmos-rock'))
  assert.deepEqual(rocks, places(again.root.getObjectByName('atmos-rock')))
  assert.equal(rocks.length, 7)
  assert.deepEqual(places(first.root.getObjectByName('atmos-ash')), places(again.root.getObjectByName('atmos-ash')))
  for (const name of ['atmos-rock', 'atmos-cone', 'atmos-vent', 'atmos-ash']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  const cone = new Matrix4()
  first.root.getObjectByName('atmos-cone').getMatrixAt(0, cone)
  assert.ok(cone.elements[5] > 0.5)
  assert.equal(first.root.getObjectByName('atmos-sun'), undefined)
  assert.equal(first.root.name, 'atmos-volcano')
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('ash falls and the heat brightens the lava', () => {
  const built = buildVolcano(resolved(), true)
  const ash = built.root.getObjectByName('atmos-ash')
  const lava = built.root.getObjectByName('atmos-lava')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const parked = places(ash)[0][1]
  const dim = lava.material.uniforms.uHeat.value
  built.handle.sync(2, {}, {}, 'low', 3, resolved({ variant: 8 }))
  assert.notEqual(places(ash)[0][1], parked)
  assert.ok(lava.material.uniforms.uHeat.value > dim)
  const cool = buildVolcano(resolved({ variant: 0 }), true)
  assert.ok(cool.root.getObjectByName('atmos-lava').material.uniforms.uHeat.value < dim)
  assert.ok(cool.root.getObjectByName('atmos-ash'))
  const calm = buildVolcano(resolved({ timeOfDay: 'calm', palette: 'ash' }, 'high'), true)
  assert.equal(calm.root.getObjectByName('atmos-rock').count, 11)
  assert.equal(calm.root.getObjectByName('atmos-ash').count, 44)
  assert.equal(calm.root.getObjectByName('atmos-sun'), undefined)
  assert.ok(calm.root.getObjectByName('atmos-lava').material.uniforms.uFlow.value < lava.material.uniforms.uFlow.value)
  built.handle.dispose()
  built.handle.dispose()
  cool.handle.dispose()
  calm.handle.dispose()
})

test('volcano degrades to a flat floor without WebGL2', () => {
  const flat = buildVolcano(resolved(), false)
  assert.equal(flat.root.name, 'atmos-volcano')
  assert.equal(flat.root.getObjectByName('atmos-lava'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-ash'), undefined)
  assert.equal(flat.root.children.length, 1)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-volcano-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [196, 50, 40])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
