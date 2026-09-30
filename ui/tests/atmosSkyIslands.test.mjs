import assert from 'node:assert/strict'
import test from 'node:test'
import { Box3, Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildSkyIslands } from '../src/features/scene3d/atmos/sets/skyIslands.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'peach', timeOfDay: 'clear', variant: 5, ...patch }, 'atmos-sky-islands'), quality, 'atmos-sky-islands')
}

function places(mesh) {
  const matrix = new Matrix4()
  const spots = []
  for (let i = 0; i < mesh.count; i += 1) {
    mesh.getMatrixAt(i, matrix)
    spots.push([matrix.elements[12], matrix.elements[13], matrix.elements[14], matrix.elements[0], matrix.elements[5]])
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

function onIsland(box, x, z) {
  return x >= box.min.x && x <= box.max.x && z >= box.min.z && z <= box.max.z
}

test('sky island templates keep peach, clear sky, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-sky-islands-wide')
  const low = atmosTemplateDocument('atmos-sky-islands-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-sky-islands')
    assert.equal(doc.atmos?.timeOfDay, 'clear')
    assert.equal(doc.atmos?.palette, 'peach')
    assert.equal(doc.atmos?.variant, 5)
    assert.deepEqual([...doc.light.direction], [0.18, -0.9, -0.38])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
  }
  assert.deepEqual([...wide.camera.eye], [0.55, 2.45, 5.9])
  assert.equal(wide.camera.fov, 52)
  assert.deepEqual([...low.camera.eye], [0.72, 1.25, 2.35])
  assert.equal(low.camera.fov, 50)
  assert.equal(settingFromDressing('atmos-sky-islands'), 'islands')
  assert.equal(parseAtmosSettings({ palette: 'peach', timeOfDay: 'pink', variant: 20 }, 'atmos-sky-islands')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'mint', variant: -1 }, 'atmos-sky-islands')?.variant, 0)
  assert.equal(resolved().seed, 95017)
})

test('the main island holds the circle and the lane, and coins and clouds stay off both', () => {
  const first = buildSkyIslands(resolved(), true)
  const again = buildSkyIslands(resolved(), true)
  const coins = places(first.root.getObjectByName('atmos-coin'))
  assert.deepEqual(coins, places(again.root.getObjectByName('atmos-coin')))
  assert.ok(coins.length >= 6)
  first.root.updateWorldMatrix(true, true)
  const island = first.root.getObjectByName('atmos-island')
  const box = new Box3().setFromObject(island)
  assert.ok(Math.abs(box.min.y) < 0.02 && Math.abs(box.max.y) < 0.02)
  assert.ok(box.max.x - box.min.x < 12)
  assert.ok(onIsland(box, CLEARING_SUBJECT[0], CLEARING_SUBJECT[2]))
  for (let i = 0; i < 8; i += 1) {
    const angle = (i / 8) * Math.PI * 2
    assert.equal(onIsland(box, CLEARING_SUBJECT[0] + Math.cos(angle) * 1.4, CLEARING_SUBJECT[2] + Math.sin(angle) * 1.4), true)
  }
  for (const [x, z] of [[-1.05, -1.15], [1.7, -1.15], [-1.05, 3.5], [1.7, 3.5]]) {
    assert.equal(onIsland(box, x, z), true)
  }
  assert.ok(island.geometry.attributes.normal.getY(0) > 0.9)
  for (const name of ['atmos-coin', 'atmos-cloud']) {
    for (const [x, y, z] of places(first.root.getObjectByName(name))) {
      assert.equal(outsideLane(x, z), true, name)
      assert.ok(y > 0.4, name)
    }
  }
  assert.equal(first.root.getObjectByName('atmos-isle').count, 4)
  assert.equal(first.root.getObjectByName('atmos-star').count, 22)
  assert.equal(first.root.getObjectByName('atmos-sun'), undefined)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('coins spin in place and pink mint retints the sky', () => {
  const built = buildSkyIslands(resolved(), true)
  const coins = built.root.getObjectByName('atmos-coin')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const parked = places(coins)[0]
  built.handle.sync(0.8, {}, {}, 'low', 3, resolved({ variant: 8 }))
  const spun = places(coins)[0]
  assert.equal(spun[0], parked[0])
  assert.equal(spun[1], parked[1])
  assert.equal(spun[2], parked[2])
  assert.ok(Math.abs(spun[4] - 1) < 1e-4)
  assert.notEqual(spun[3], parked[3])
  const calm = buildSkyIslands(resolved({ variant: 0 }), true)
  const still = calm.root.getObjectByName('atmos-coin')
  calm.handle.sync(0, {}, {}, 'low', 3, resolved({ variant: 0 }))
  const held = places(still)[0][3]
  calm.handle.sync(1.2, {}, {}, 'low', 3, resolved({ variant: 0 }))
  assert.equal(places(still)[0][3], held)
  const pink = buildSkyIslands(resolved({ timeOfDay: 'pink', palette: 'mint' }, 'high'), true)
  assert.equal(pink.root.getObjectByName('atmos-coin').count, 12)
  assert.equal(pink.root.getObjectByName('atmos-star').count, 36)
  assert.equal(pink.root.getObjectByName('atmos-sky').material.uniforms.uZenith.value.getHexString(), '3a1454')
  built.handle.dispose()
  built.handle.dispose()
  calm.handle.dispose()
  pink.handle.dispose()
})

test('sky islands degrade to a flat pad without WebGL2', () => {
  const flat = buildSkyIslands(resolved(), false)
  assert.equal(flat.root.name, 'atmos-sky-islands')
  assert.equal(flat.root.children[0].name, 'atmos-sky-islands')
  assert.equal(flat.root.getObjectByName('atmos-island'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-coin'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-sky-islands-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [255, 196, 154])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
