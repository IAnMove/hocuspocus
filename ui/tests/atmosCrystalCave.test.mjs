import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildCrystalCave } from '../src/features/scene3d/atmos/sets/crystalCave.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'amethyst', timeOfDay: 'deep', variant: 5, ...patch }, 'atmos-crystal-cave'), quality, 'atmos-crystal-cave')
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

test('crystal cave templates keep amethyst, deep shade, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-crystal-cave-wide')
  const low = atmosTemplateDocument('atmos-crystal-cave-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-crystal-cave')
    assert.equal(doc.atmos?.timeOfDay, 'deep')
    assert.equal(doc.atmos?.palette, 'amethyst')
    assert.equal(doc.atmos?.variant, 5)
    assert.deepEqual([...doc.light.direction], [0.05, -0.95, -0.12])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
  }
  assert.deepEqual([...wide.camera.eye], [0.15, 1.48, 3.9])
  assert.equal(wide.camera.fov, 52)
  assert.deepEqual([...low.camera.eye], [0.55, 0.62, 2.35])
  assert.equal(low.camera.fov, 56)
  assert.equal(settingFromDressing('atmos-crystal-cave'), 'cave')
  assert.equal(parseAtmosSettings({ palette: 'amethyst', timeOfDay: 'glow', variant: 20 }, 'atmos-crystal-cave')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'aqua', variant: -1 }, 'atmos-crystal-cave')?.variant, 0)
})

test('crystals, rocks, drips and motes stay off the lane', () => {
  const first = buildCrystalCave(resolved(), true)
  const again = buildCrystalCave(resolved(), true)
  const crystals = places(first.root.getObjectByName('atmos-crystal'))
  assert.deepEqual(crystals, places(again.root.getObjectByName('atmos-crystal')))
  assert.ok(crystals.length >= 6)
  for (const name of ['atmos-crystal', 'atmos-ceiling', 'atmos-rock', 'atmos-drip', 'atmos-mote']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  const floor = new Matrix4()
  const ceiling = new Matrix4()
  first.root.getObjectByName('atmos-crystal').getMatrixAt(0, floor)
  first.root.getObjectByName('atmos-ceiling').getMatrixAt(0, ceiling)
  assert.ok(floor.elements[5] > 0.5)
  assert.ok(ceiling.elements[5] < -0.5)
  assert.equal(first.root.getObjectByName('atmos-sun'), undefined)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('drips fall and the glow brightens the crystals', () => {
  const built = buildCrystalCave(resolved(), true)
  const drips = built.root.getObjectByName('atmos-drip')
  const crystals = built.root.getObjectByName('atmos-crystal')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const parked = places(drips)[0][1]
  const dim = crystals.instanceColor.getX(0)
  built.handle.sync(2, {}, {}, 'low', 3, resolved({ variant: 8 }))
  assert.notEqual(places(drips)[0][1], parked)
  assert.ok(crystals.instanceColor.getX(0) > dim)
  const calm = buildCrystalCave(resolved({ variant: 0 }), true)
  assert.ok(calm.root.getObjectByName('atmos-crystal').instanceColor.getX(0) < dim)
  assert.ok(calm.root.getObjectByName('atmos-drip'))
  const glow = buildCrystalCave(resolved({ timeOfDay: 'glow', palette: 'aqua' }, 'high'), true)
  assert.equal(glow.root.getObjectByName('atmos-crystal').count, 12)
  assert.equal(glow.root.getObjectByName('atmos-sun'), undefined)
  built.handle.dispose()
  built.handle.dispose()
  calm.handle.dispose()
  glow.handle.dispose()
})

test('crystal cave degrades to a flat floor without WebGL2', () => {
  const flat = buildCrystalCave(resolved(), false)
  assert.equal(flat.root.getObjectByName('atmos-crystal'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-drip'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-crystal-cave-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [42, 24, 68])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
