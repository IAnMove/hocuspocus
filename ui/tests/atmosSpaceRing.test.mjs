import assert from 'node:assert/strict'
import test from 'node:test'
import { DoubleSide, Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildSpaceRing } from '../src/features/scene3d/atmos/sets/spaceRing.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'ice', timeOfDay: 'cruise', variant: 4, ...patch }, 'atmos-space-ring'), quality, 'atmos-space-ring')
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

function moved(variant) {
  const built = buildSpaceRing(resolved({ variant }), true)
  const mesh = built.root.getObjectByName('atmos-asteroid')
  const start = places(mesh)[0]
  built.handle.sync(2, {}, {}, 'low', 3, resolved({ variant }))
  const next = places(mesh)[0]
  built.handle.dispose()
  return Math.hypot(next[0] - start[0], next[2] - start[2])
}

function tiltOf(variant) {
  const built = buildSpaceRing(resolved({ variant }), true)
  const tilt = built.root.getObjectByName('atmos-ring').rotation.x
  built.handle.dispose()
  return tilt
}

test('space ring templates keep ice, cruise, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-space-ring-wide')
  const low = atmosTemplateDocument('atmos-space-ring-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-space-ring')
    assert.equal(doc.atmos?.timeOfDay, 'cruise')
    assert.equal(doc.atmos?.palette, 'ice')
    assert.equal(doc.atmos?.variant, 4)
    assert.deepEqual([...doc.light.direction], [-0.38, -0.58, -0.72])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.22, 1.55, 3.15])
  assert.equal(wide.camera.fov, 50)
  assert.deepEqual([...low.camera.eye], [0.7, 0.32, 0.85])
  assert.equal(low.camera.fov, 58)
  assert.equal(settingFromDressing('atmos-space-ring'), 'space')
  assert.equal(parseAtmosSettings({ palette: 'ice', timeOfDay: 'eclipse', variant: 20 }, 'atmos-space-ring')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'copper', variant: -1 }, 'atmos-space-ring')?.variant, 0)
})

test('asteroids stay off the lane and the pad holds the subject', () => {
  const first = buildSpaceRing(resolved(), true)
  const again = buildSpaceRing(resolved(), true)
  const rocks = places(first.root.getObjectByName('atmos-asteroid'))
  assert.deepEqual(rocks, places(again.root.getObjectByName('atmos-asteroid')))
  assert.equal(rocks.length, 14)
  assert.equal(first.root.getObjectByName('atmos-asteroid').isInstancedMesh, true)
  for (const [x, , z] of rocks) assert.equal(outsideLane(x, z), true)
  const pad = first.root.getObjectByName('atmos-pad')
  assert.equal(pad.position.x, CLEARING_SUBJECT[0])
  assert.equal(pad.position.z, CLEARING_SUBJECT[2])
  assert.equal(pad.position.y, -0.08)
  const body = first.root.getObjectByName('atmos-body')
  assert.ok(body.position.z < -10)
  assert.ok(body.position.y > 2)
  assert.equal(first.root.getObjectByName('atmos-ring-a').material.side, DoubleSide)
  assert.equal(first.root.getObjectByName('atmos-ring-b').material.side, DoubleSide)
  assert.equal(first.root.getObjectByName('atmos-sun'), undefined)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.sync(3, {}, {}, 'low', 3, resolved())
  for (const [x, , z] of places(first.root.getObjectByName('atmos-asteroid'))) assert.equal(outsideLane(x, z), true)
  first.handle.dispose()
  again.handle.dispose()
})

test('orbit tilts the rings and speeds the asteroid drift', () => {
  assert.ok(tiltOf(0) > tiltOf(4))
  assert.ok(tiltOf(4) > tiltOf(8))
  assert.ok(moved(8) > moved(0))
  const built = buildSpaceRing(resolved(), true)
  const dim = built.root.getObjectByName('atmos-planet').material.uniforms.uEclipse.value
  assert.equal(dim, 0)
  built.handle.sync(1, {}, {}, 'low', 3, resolved({ variant: 0 }))
  const slow = places(built.root.getObjectByName('atmos-asteroid'))[0]
  built.handle.sync(1, {}, {}, 'low', 3, resolved({ variant: 8 }))
  const fast = places(built.root.getObjectByName('atmos-asteroid'))[0]
  assert.ok(Math.hypot(fast[0] - slow[0], fast[2] - slow[2]) > 0)
  assert.ok(built.root.getObjectByName('atmos-ring').rotation.x < tiltOf(4))
  const eclipse = buildSpaceRing(resolved({ timeOfDay: 'eclipse', palette: 'copper' }, 'high'), true)
  const planet = eclipse.root.getObjectByName('atmos-planet').material
  assert.equal(planet.uniforms.uEclipse.value, 1)
  assert.notEqual(planet.uniforms.uLit.value.getHexString(), built.root.getObjectByName('atmos-planet').material.uniforms.uLit.value.getHexString())
  assert.equal(eclipse.root.getObjectByName('atmos-asteroid').count, 22)
  assert.equal(eclipse.root.getObjectByName('atmos-sun'), undefined)
  built.handle.dispose()
  built.handle.dispose()
  eclipse.handle.dispose()
})

test('space ring degrades to a flat pad without WebGL2', () => {
  const flat = buildSpaceRing(resolved(), false)
  assert.equal(flat.root.name, 'atmos-space-ring')
  assert.ok(flat.root.getObjectByName('atmos-pad'))
  assert.equal(flat.root.getObjectByName('atmos-asteroid'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-planet'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-space-ring-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [5, 7, 14])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
