import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildRooftopNight } from '../src/features/scene3d/atmos/sets/rooftopNight.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'sodium', timeOfDay: 'night', variant: 5, ...patch }, 'atmos-rooftop-night'), quality, 'atmos-rooftop-night')
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

function brightWindows(mesh) {
  let lit = 0
  for (let index = 0; index < mesh.count; index += 1) {
    if (mesh.instanceColor.getX(index) > 0.4) lit += 1
  }
  return lit
}

test('rooftop night templates keep sodium, night, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-rooftop-night-wide')
  const low = atmosTemplateDocument('atmos-rooftop-night-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-rooftop-night')
    assert.equal(doc.atmos?.timeOfDay, 'night')
    assert.equal(doc.atmos?.palette, 'sodium')
    assert.equal(doc.atmos?.variant, 5)
    assert.deepEqual([...doc.light.direction], [0.12, -0.96, -0.18])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.2, 1.65, 4.6])
  assert.equal(wide.camera.fov, 58)
  assert.deepEqual([...low.camera.eye], [0.85, 0.55, 2.4])
  assert.equal(low.camera.fov, 60)
  assert.equal(settingFromDressing('atmos-rooftop-night'), 'rooftop')
  assert.equal(parseAtmosSettings({ palette: 'sodium', timeOfDay: 'late', variant: 20 }, 'atmos-rooftop-night')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'indigo', variant: -1 }, 'atmos-rooftop-night')?.variant, 0)
  assert.equal(parseAtmosSettings({ timeOfDay: 'noon' }, 'atmos-rooftop-night')?.timeOfDay, 'night')
})

test('vents, aerials and the parapet stay off the lane', () => {
  const first = buildRooftopNight(resolved(), true)
  const again = buildRooftopNight(resolved(), true)
  const windows = places(first.root.getObjectByName('atmos-window'))
  assert.deepEqual(windows, places(again.root.getObjectByName('atmos-window')))
  assert.ok(windows.length >= 24)
  for (const name of ['atmos-vent', 'atmos-aerial', 'atmos-parapet', 'atmos-window', 'atmos-tower']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  for (const [, y, z] of windows) {
    assert.ok(y > 1)
    assert.ok(z < -8)
  }
  const ground = first.root.getObjectByName('atmos-ground')
  ground.geometry.computeBoundingBox()
  const box = ground.geometry.boundingBox
  assert.ok(box.max.y - box.min.y < 0.01)
  assert.ok(box.max.x - box.min.x > 10)
  assert.ok(box.max.z - box.min.z > 10)
  assert.equal(first.root.getObjectByName('atmos-window').material.type, 'MeshBasicMaterial')
  assert.equal(first.root.getObjectByName('atmos-sun'), undefined)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('the skyline lights more windows and the aerials sway', () => {
  const built = buildRooftopNight(resolved(), true)
  const windows = built.root.getObjectByName('atmos-window')
  const aerials = built.root.getObjectByName('atmos-aerial')
  const sky = built.root.getObjectByName('atmos-sky')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const dim = windows.instanceColor.getX(0)
  const lit = brightWindows(windows)
  const matrix = new Matrix4()
  aerials.getMatrixAt(0, matrix)
  const parked = matrix.elements[6]
  built.handle.sync(2, {}, {}, 'low', 3, resolved({ variant: 8 }))
  assert.ok(windows.instanceColor.getX(0) > dim)
  assert.ok(brightWindows(windows) > lit)
  aerials.getMatrixAt(0, matrix)
  assert.notEqual(matrix.elements[6], parked)
  const calm = buildRooftopNight(resolved({ variant: 0 }), true)
  assert.ok(calm.root.getObjectByName('atmos-window').instanceColor.getX(0) < dim)
  assert.ok(brightWindows(calm.root.getObjectByName('atmos-window')) < lit)
  built.handle.sync(1, {}, {}, 'low', 3, resolved({ timeOfDay: 'late', palette: 'indigo' }))
  assert.equal(sky.material.uniforms.uZenith.value.getHexString(), '243456')
  assert.equal(sky.material.uniforms.uHorizon.value.getHexString(), '1c2c4e')
  const full = buildRooftopNight(resolved({ timeOfDay: 'late', palette: 'indigo' }, 'high'), true)
  assert.ok(full.root.getObjectByName('atmos-window').count > windows.count)
  assert.equal(full.root.getObjectByName('atmos-tower').count, 8)
  assert.equal(full.root.getObjectByName('atmos-sun'), undefined)
  built.handle.dispose()
  built.handle.dispose()
  calm.handle.dispose()
  full.handle.dispose()
})

test('rooftop night degrades to a flat roof without WebGL2', () => {
  const flat = buildRooftopNight(resolved(), false)
  assert.equal(flat.root.name, 'atmos-rooftop-night')
  assert.equal(flat.root.getObjectByName('atmos-window'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-vent'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-aerial'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-parapet'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-rooftop-night-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [58, 38, 28])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
