import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildMoon } from '../src/features/scene3d/atmos/sets/moon.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'regolith', timeOfDay: 'day', variant: 18, ...patch }, 'atmos-moon'), quality, 'atmos-moon')
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

test('moon templates keep regolith, day, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-moon-wide')
  const low = atmosTemplateDocument('atmos-moon-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-moon')
    assert.equal(doc.atmos?.timeOfDay, 'day')
    assert.equal(doc.atmos?.palette, 'regolith')
    assert.equal(doc.atmos?.variant, 18)
    assert.deepEqual([...doc.light.direction], [-0.25, -0.16, -0.92])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
  }
  assert.deepEqual([...wide.camera.eye], [0.15, 1.28, 3.7])
  assert.equal(wide.camera.fov, 48)
  assert.deepEqual([...low.camera.eye], [1.4, 0.38, 1.85])
  assert.equal(low.camera.fov, 52)
  assert.equal(settingFromDressing('atmos-moon'), 'moon')
  const clamped = parseAtmosSettings({ palette: 'regolith', timeOfDay: 'earthrise', variant: 80 }, 'atmos-moon')
  assert.equal(clamped?.variant, 40)
  assert.equal(parseAtmosSettings({ palette: 'basalt', variant: 1 }, 'atmos-moon')?.variant, 8)
})

test('moon props stay off the lane and the long shadow follows the sun', () => {
  const first = buildMoon(resolved(), true)
  const again = buildMoon(resolved(), true)
  const rocks = places(first.root.getObjectByName('atmos-rock'))
  assert.deepEqual(rocks, places(again.root.getObjectByName('atmos-rock')))
  assert.ok(rocks.length >= 8)
  for (const [x, , z] of rocks) assert.equal(outsideLane(x, z), true)
  for (const [x, , z] of places(first.root.getObjectByName('atmos-crater'))) assert.equal(outsideLane(x, z), true)
  for (const [x, , z] of places(first.root.getObjectByName('atmos-leg'))) assert.equal(outsideLane(x, z), true)
  for (const [x, , z] of places(first.root.getObjectByName('atmos-print'))) assert.equal(outsideLane(x, z), true)
  const lander = first.root.getObjectByName('atmos-lander')
  assert.equal(outsideLane(lander.position.x, lander.position.z), true)
  const ground = first.root.getObjectByName('atmos-ground').geometry.getAttribute('normal')
  let up = 0
  for (let i = 0; i < ground.count; i += 1) if (ground.getY(i) > 0.2) up += 1
  assert.ok(up > ground.count * 0.8)
  const rim = first.root.getObjectByName('atmos-rim')
  const rimMatrix = new Matrix4()
  rim.getMatrixAt(0, rimMatrix)
  assert.ok(rimMatrix.elements[9] > 0.5)
  const shadowMesh = first.root.getObjectByName('atmos-shadow')
  const shadowMatrix = new Matrix4()
  shadowMesh.getMatrixAt(0, shadowMatrix)
  assert.ok(shadowMatrix.elements[9] > 0.5)
  const shadows = places(shadowMesh)
  const sun = resolved().sun
  const span = Math.hypot(sun[0], sun[2])
  const along = (shadows[0][0] - rocks[0][0]) * sun[0] / span + (shadows[0][2] - rocks[0][2]) * sun[2] / span
  assert.ok(along > 0.4)
  const risen = buildMoon(resolved({ timeOfDay: 'earthrise' }), true)
  assert.ok(first.root.getObjectByName('atmos-shadow').userData.reach > risen.root.getObjectByName('atmos-shadow').userData.reach)
  assert.ok(first.root.getObjectByName('atmos-earth').position.y > risen.root.getObjectByName('atmos-earth').position.y)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh || obj.isPoints) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
  risen.handle.dispose()
})

test('earth keeps turning and earthrise lowers it', () => {
  const built = buildMoon(resolved(), true)
  const earth = built.root.getObjectByName('atmos-earth')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const start = earth.rotation.y
  built.handle.sync(2, {}, {}, 'low', 3, resolved())
  assert.ok(earth.rotation.y > start + 0.1)
  assert.ok(earth.material.uniforms.uTime.value > 1)
  assert.equal(built.root.getObjectByName('atmos-print').count, 18)
  const many = buildMoon(resolved({ variant: 40, palette: 'basalt' }), true)
  assert.equal(many.root.getObjectByName('atmos-print').count, 40)
  assert.equal(many.root.getObjectByName('atmos-earth').position.y < built.root.getObjectByName('atmos-earth').position.y, false)
  built.handle.dispose()
  built.handle.dispose()
  many.handle.dispose()
})

test('moon degrades to a flat plain without WebGL2', () => {
  const flat = buildMoon(resolved(), false)
  assert.equal(flat.root.getObjectByName('atmos-earth'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-moon-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [7, 8, 14])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
