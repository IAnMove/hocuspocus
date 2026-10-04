import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildWaterfall } from '../src/features/scene3d/atmos/sets/waterfall.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'moss', timeOfDay: 'golden', variant: 60, ...patch }, 'atmos-waterfall'), quality, 'atmos-waterfall')
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

test('waterfall templates keep moss, golden hour and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-waterfall-wide')
  const low = atmosTemplateDocument('atmos-waterfall-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-waterfall')
    assert.equal(doc.atmos?.timeOfDay, 'golden')
    assert.equal(doc.atmos?.palette, 'moss')
    assert.equal(doc.atmos?.variant, 60)
    assert.deepEqual([...doc.light.direction], [0.82, -0.55, 0.16])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
  }
  assert.deepEqual([...wide.camera.eye], [0.2, 1.42, 3.55])
  assert.equal(wide.camera.fov, 40)
  assert.deepEqual([...low.camera.eye], [1.35, 0.46, 1.85])
  assert.equal(low.camera.fov, 46)
  assert.equal(settingFromDressing('atmos-waterfall'), 'canyon')
  const clamped = parseAtmosSettings({ palette: 'moss', timeOfDay: 'morning', variant: 400 }, 'atmos-waterfall')
  assert.equal(clamped?.variant, 100)
  assert.equal(parseAtmosSettings({ palette: 'moss', variant: 1 }, 'atmos-waterfall')?.variant, 20)
})

test('waterfall props stay off the bank and the sheet faces the camera', () => {
  const first = buildWaterfall(resolved(), true)
  const again = buildWaterfall(resolved(), true)
  const bushes = places(first.root.getObjectByName('atmos-bushes'))
  assert.deepEqual(bushes, places(again.root.getObjectByName('atmos-bushes')))
  assert.ok(bushes.length >= 8)
  for (const [x, , z] of bushes) assert.equal(outsideLane(x, z), true)
  for (const [x, , z] of places(first.root.getObjectByName('atmos-stone'))) assert.equal(outsideLane(x, z), true)
  for (const [x, , z] of places(first.root.getObjectByName('atmos-cliff'))) {
    assert.ok(z <= -0.7)
    assert.equal(outsideLane(x, z), true)
  }
  const dew = first.root.getObjectByName('atmos-dew').geometry.getAttribute('position')
  for (let i = 0; i < dew.count; i += 1) assert.ok(dew.getZ(i) < -1.6)
  const ground = first.root.getObjectByName('atmos-ground').geometry.getAttribute('normal')
  let up = 0
  for (let i = 0; i < ground.count; i += 1) if (ground.getY(i) > 0.2) up += 1
  assert.ok(up > ground.count * 0.8)
  const sheet = first.root.getObjectByName('atmos-sheet').geometry.getAttribute('normal')
  assert.ok(sheet.getZ(0) > 0.9)
  const river = first.root.getObjectByName('atmos-river').geometry.getAttribute('normal')
  assert.ok(river.getY(0) > 0.9)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh || obj.isPoints) draws += 1 })
  assert.ok(draws < 32)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('golden hour shows the rainbow and the water keeps moving', () => {
  const built = buildWaterfall(resolved(), true)
  const arc = built.root.getObjectByName('atmos-rainbow')
  const sheet = built.root.getObjectByName('atmos-sheet')
  assert.equal(arc.visible, true)
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const mistAtRest = places(built.root.getObjectByName('atmos-mist'))[0][1]
  const flowAtRest = sheet.material.uniforms.uFlow.value
  built.handle.sync(1.4, {}, {}, 'low', 3, resolved({ variant: 100, timeOfDay: 'morning' }))
  assert.equal(arc.visible, false)
  assert.ok(sheet.material.uniforms.uTime.value > 1)
  assert.ok(sheet.material.uniforms.uFlow.value > flowAtRest)
  assert.ok(places(built.root.getObjectByName('atmos-mist'))[0][1] !== mistAtRest)
  const morning = buildWaterfall(resolved({ timeOfDay: 'morning', palette: 'amber' }), true)
  assert.equal(morning.root.getObjectByName('atmos-rainbow').visible, false)
  built.handle.dispose()
  built.handle.dispose()
  morning.handle.dispose()
})

test('waterfall degrades to a flat bank without WebGL2', () => {
  const look = resolved()
  const flat = buildWaterfall(look, false)
  assert.equal(flat.root.getObjectByName('atmos-sheet'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-waterfall-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [201, 221, 208])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
