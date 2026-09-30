import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildTemple } from '../src/features/scene3d/atmos/sets/temple.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'jade', timeOfDay: 'mist', variant: 5, ...patch }, 'atmos-temple'), quality, 'atmos-temple')
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

function vineScale(mesh) {
  const matrix = new Matrix4()
  mesh.getMatrixAt(0, matrix)
  return Math.abs(matrix.elements[5])
}

function outsideLane(x, z) {
  const dx = x - CLEARING_SUBJECT[0]
  const dz = z - CLEARING_SUBJECT[2]
  const inCircle = dx * dx + dz * dz < 1.4 * 1.4
  const inLane = z > -1.15 && z < 3.5 && x > -1.05 && x < 1.7
  return !inCircle && !inLane
}

test('temple templates keep jade, mist, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-temple-wide')
  const low = atmosTemplateDocument('atmos-temple-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-temple')
    assert.equal(doc.atmos?.timeOfDay, 'mist')
    assert.equal(doc.atmos?.palette, 'jade')
    assert.equal(doc.atmos?.variant, 5)
    assert.deepEqual([...doc.light.direction], [0.08, -0.96, 0.24])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.15, 1.5, 4.2])
  assert.equal(wide.camera.fov, 52)
  assert.deepEqual([...low.camera.eye], [2.15, 0.62, 2.45])
  assert.equal(low.camera.fov, 56)
  assert.equal(settingFromDressing('atmos-temple'), 'jungle')
  assert.equal(parseAtmosSettings({ palette: 'jade', timeOfDay: 'sun', variant: 20 }, 'atmos-temple')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'vine', variant: -1 }, 'atmos-temple')?.variant, 0)
})

test('ruins, vines, butterflies and shafts stay off the lane', () => {
  const first = buildTemple(resolved(), true)
  const again = buildTemple(resolved(), true)
  const wings = places(first.root.getObjectByName('atmos-butterfly'))
  assert.deepEqual(wings, places(again.root.getObjectByName('atmos-butterfly')))
  assert.ok(wings.length >= 6)
  for (const name of ['atmos-column', 'atmos-ruin', 'atmos-moss', 'atmos-vine', 'atmos-butterfly', 'atmos-shaft', 'atmos-trunk', 'atmos-canopy']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  const hanging = new Matrix4()
  first.root.getObjectByName('atmos-vine').getMatrixAt(0, hanging)
  assert.ok(hanging.elements[5] < -0.2)
  assert.equal(first.root.name, 'atmos-temple')
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 150)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('butterflies move and growth lengthens the vines', () => {
  const built = buildTemple(resolved(), true)
  const wings = built.root.getObjectByName('atmos-butterfly')
  const vines = built.root.getObjectByName('atmos-vine')
  const shafts = built.root.getObjectByName('atmos-shaft')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const parked = places(wings)[0][0]
  const parkedShaft = places(shafts)[0][0]
  const grown = vineScale(vines)
  built.handle.sync(2, {}, {}, 'low', 3, resolved({ variant: 8 }))
  assert.notEqual(places(wings)[0][0], parked)
  assert.notEqual(places(shafts)[0][0], parkedShaft)
  assert.ok(vineScale(vines) > grown)
  const calm = buildTemple(resolved({ variant: 0 }), true)
  assert.ok(vineScale(calm.root.getObjectByName('atmos-vine')) < grown)
  assert.ok(calm.root.getObjectByName('atmos-butterfly'))
  const sunny = buildTemple(resolved({ timeOfDay: 'sun', palette: 'vine' }, 'high'), true)
  assert.equal(sunny.root.getObjectByName('atmos-butterfly').count, 12)
  assert.equal(sunny.root.getObjectByName('atmos-vine').count, 8)
  assert.ok(sunny.root.getObjectByName('atmos-sun'))
  built.handle.dispose()
  built.handle.dispose()
  calm.handle.dispose()
  sunny.handle.dispose()
})

test('temple degrades to a flat floor without WebGL2', () => {
  const flat = buildTemple(resolved(), false)
  assert.equal(flat.root.name, 'atmos-temple')
  assert.equal(flat.root.children.length, 1)
  assert.equal(flat.root.getObjectByName('atmos-butterfly'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-shaft'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-vine'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-temple-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [213, 226, 196])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
