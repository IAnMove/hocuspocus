import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildSiliconGrid } from '../src/features/scene3d/atmos/sets/siliconGrid.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'outrun', timeOfDay: 'dusk', variant: 4, ...patch }, 'atmos-silicon-grid'), quality, 'atmos-silicon-grid')
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

function gridScroll(variant, seconds) {
  const built = buildSiliconGrid(resolved({ variant }), true)
  built.handle.sync(seconds, {}, {}, 'low', 3, resolved({ variant }))
  const scroll = built.root.getObjectByName('atmos-grid').material.uniforms.uScroll.value
  const density = built.root.getObjectByName('atmos-grid').material.uniforms.uDensity.value
  built.handle.dispose()
  return { scroll, density }
}

test('silicon grid templates keep outrun, dusk, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-silicon-grid-wide')
  const low = atmosTemplateDocument('atmos-silicon-grid-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-silicon-grid')
    assert.equal(doc.atmos?.timeOfDay, 'dusk')
    assert.equal(doc.atmos?.palette, 'outrun')
    assert.equal(doc.atmos?.variant, 4)
    assert.deepEqual([...doc.light.direction], [0.04, -0.42, -0.91])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.2, 1.35, 3.4])
  assert.equal(wide.camera.fov, 48)
  assert.deepEqual([...low.camera.eye], [0.85, 0.28, 0.35])
  assert.equal(low.camera.fov, 56)
  assert.equal(settingFromDressing('atmos-silicon-grid'), 'grid')
  assert.equal(parseAtmosSettings({ palette: 'outrun', timeOfDay: 'night', variant: 20 }, 'atmos-silicon-grid')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'chrome', variant: -1 }, 'atmos-silicon-grid')?.variant, 0)
})

test('wire mountains stay off the lane and the pad holds the subject', () => {
  const first = buildSiliconGrid(resolved(), true)
  const again = buildSiliconGrid(resolved(), true)
  const peaks = places(first.root.getObjectByName('atmos-peak'))
  assert.deepEqual(peaks, places(again.root.getObjectByName('atmos-peak')))
  assert.equal(peaks.length, 8)
  assert.equal(first.root.getObjectByName('atmos-peak').isInstancedMesh, true)
  assert.equal(first.root.getObjectByName('atmos-wire').count, 8)
  for (const [x, , z] of peaks) assert.equal(outsideLane(x, z), true)
  const pad = first.root.getObjectByName('atmos-pad')
  assert.equal(pad.position.x, CLEARING_SUBJECT[0])
  assert.equal(pad.position.z, CLEARING_SUBJECT[2])
  assert.equal(first.root.getObjectByName('atmos-star').geometry.getAttribute('position').count, 36)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh || obj.isPoints) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('variant densifies the grid and night sinks the sun', () => {
  const slow = gridScroll(0, 2)
  const fast = gridScroll(8, 2)
  assert.ok(fast.density > slow.density)
  assert.ok(fast.scroll > slow.scroll)
  const again = gridScroll(8, 2)
  assert.equal(again.scroll, fast.scroll)
  const dusk = buildSiliconGrid(resolved(), true)
  const night = buildSiliconGrid(resolved({ timeOfDay: 'night', palette: 'chrome' }, 'high'), true)
  assert.ok(night.root.getObjectByName('atmos-sun').position.y < dusk.root.getObjectByName('atmos-sun').position.y)
  assert.equal(night.root.getObjectByName('atmos-peak').count, 14)
  assert.equal(night.root.getObjectByName('atmos-star').geometry.getAttribute('position').count, 72)
  dusk.handle.sync(1, {}, {}, 'low', 3, resolved({ timeOfDay: 'night' }))
  assert.ok(dusk.root.getObjectByName('atmos-grid').material.uniforms.uGain.value > 1)
  dusk.handle.dispose()
  night.handle.dispose()
})

test('silicon grid degrades to a flat pad without WebGL2', () => {
  const flat = buildSiliconGrid(resolved(), false)
  assert.equal(flat.root.name, 'atmos-silicon-grid')
  assert.ok(flat.root.getObjectByName('atmos-pad'))
  assert.equal(flat.root.getObjectByName('atmos-grid'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-sun'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-silicon-grid-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [18, 4, 88])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
