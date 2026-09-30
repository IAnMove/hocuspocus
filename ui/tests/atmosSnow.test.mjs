import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildSnow } from '../src/features/scene3d/atmos/sets/snow.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'frost', timeOfDay: 'blue', variant: 36, ...patch }, 'atmos-snow'), quality, 'atmos-snow')
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

test('snow templates keep frost, blue hour, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-snow-wide')
  const low = atmosTemplateDocument('atmos-snow-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-snow')
    assert.equal(doc.atmos?.timeOfDay, 'blue')
    assert.equal(doc.atmos?.palette, 'frost')
    assert.equal(doc.atmos?.variant, 36)
    assert.deepEqual([...doc.light.direction], [-0.42, -0.22, -0.78])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
  }
  assert.deepEqual([...wide.camera.eye], [0.12, 1.55, 4.15])
  assert.equal(wide.camera.fov, 46)
  assert.deepEqual([...low.camera.eye], [1.15, 0.42, 2.05])
  assert.equal(low.camera.fov, 52)
  assert.equal(settingFromDressing('atmos-snow'), 'snow')
  assert.equal(parseAtmosSettings({ palette: 'frost', timeOfDay: 'day', variant: 100 }, 'atmos-snow')?.variant, 80)
  assert.equal(parseAtmosSettings({ palette: 'twilight', variant: -3 }, 'atmos-snow')?.variant, 0)
})

test('snow props stay off the lane and footprints lie flat', () => {
  const first = buildSnow(resolved(), true)
  const again = buildSnow(resolved(), true)
  const pines = places(first.root.getObjectByName('atmos-pine'))
  assert.deepEqual(pines, places(again.root.getObjectByName('atmos-pine')))
  assert.ok(pines.length >= 6)
  for (const name of ['atmos-pine', 'atmos-trunk', 'atmos-cap', 'atmos-print']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  const cabin = first.root.getObjectByName('atmos-cabin')
  assert.equal(outsideLane(cabin.position.x, cabin.position.z), true)
  const ground = first.root.getObjectByName('atmos-ground').geometry.getAttribute('normal')
  let up = 0
  for (let i = 0; i < ground.count; i += 1) if (ground.getY(i) > 0.2) up += 1
  assert.ok(up > ground.count * 0.8)
  const prints = first.root.getObjectByName('atmos-print')
  const normal = prints.geometry.getAttribute('normal')
  let facing = 0
  for (let i = 0; i < normal.count; i += 1) if (normal.getY(i) > 0.5) facing += 1
  assert.ok(facing === normal.count)
  const aurora = first.root.getObjectByName('atmos-aurora')
  assert.equal(aurora.rotation.x, 0)
  assert.equal(aurora.rotation.y, 0)
  assert.ok(aurora.position.z < -10)
  const day = buildSnow(resolved({ timeOfDay: 'day' }), true)
  assert.equal(day.root.getObjectByName('atmos-aurora'), undefined)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh || obj.isPoints) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
  day.handle.dispose()
})

test('two flake layers fall and blue hour keeps the aurora', () => {
  const built = buildSnow(resolved(), true)
  const near = built.root.getObjectByName('atmos-near')
  const far = built.root.getObjectByName('atmos-far')
  assert.equal(near.geometry.getAttribute('position').count, 36)
  assert.equal(far.geometry.getAttribute('position').count, 72)
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  built.handle.sync(2, {}, {}, 'low', 3, resolved())
  assert.ok(near.material.uniforms.uTime.value > 1)
  assert.ok(far.material.uniforms.uTime.value > 1)
  assert.ok(built.root.getObjectByName('atmos-aurora').material.uniforms.uTime.value > 1)
  const many = buildSnow(resolved({ variant: 80, palette: 'twilight' }), true)
  assert.equal(many.root.getObjectByName('atmos-near').geometry.getAttribute('position').count, 80)
  const none = buildSnow(resolved({ variant: 0 }), true)
  assert.equal(none.root.getObjectByName('atmos-near'), undefined)
  assert.ok(none.root.getObjectByName('atmos-aurora'))
  built.handle.dispose()
  built.handle.dispose()
  many.handle.dispose()
  none.handle.dispose()
})

test('snow degrades to a flat field without WebGL2', () => {
  const flat = buildSnow(resolved(), false)
  assert.equal(flat.root.getObjectByName('atmos-aurora'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-pine'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-snow-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [212, 226, 240])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
