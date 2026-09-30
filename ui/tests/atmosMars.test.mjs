import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildMars } from '../src/features/scene3d/atmos/sets/mars.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'rust', timeOfDay: 'noon', variant: 3, ...patch }, 'atmos-mars'), quality, 'atmos-mars')
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

test('mars templates keep rust, noon, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-mars-wide')
  const low = atmosTemplateDocument('atmos-mars-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-mars')
    assert.equal(doc.atmos?.timeOfDay, 'noon')
    assert.equal(doc.atmos?.palette, 'rust')
    assert.equal(doc.atmos?.variant, 3)
    assert.deepEqual([...doc.light.direction], [0.2, -0.78, -0.48])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
  }
  assert.deepEqual([...wide.camera.eye], [0.1, 1.45, 4.0])
  assert.equal(wide.camera.fov, 48)
  assert.deepEqual([...low.camera.eye], [1.35, 0.42, 1.9])
  assert.equal(low.camera.fov, 54)
  assert.equal(settingFromDressing('atmos-mars'), 'desert')
  assert.equal(parseAtmosSettings({ palette: 'rust', timeOfDay: 'dusk', variant: 20 }, 'atmos-mars')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'dusk', variant: -2 }, 'atmos-mars')?.variant, 0)
})

test('mars props stay off the lane and the rover shadow follows the sun', () => {
  const first = buildMars(resolved(), true)
  const again = buildMars(resolved(), true)
  const rocks = places(first.root.getObjectByName('atmos-rock'))
  assert.deepEqual(rocks, places(again.root.getObjectByName('atmos-rock')))
  assert.ok(rocks.length >= 6)
  for (const name of ['atmos-rock', 'atmos-strata', 'atmos-dune', 'atmos-ridge', 'atmos-wheel', 'atmos-devil']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  const rover = first.root.getObjectByName('atmos-rover')
  assert.equal(outsideLane(rover.position.x, rover.position.z), true)
  const ground = first.root.getObjectByName('atmos-ground').geometry.getAttribute('normal')
  let up = 0
  for (let i = 0; i < ground.count; i += 1) if (ground.getY(i) > 0.2) up += 1
  assert.ok(up > ground.count * 0.8)
  const shadowMesh = first.root.getObjectByName('atmos-shadow')
  const shadowMatrix = new Matrix4()
  shadowMesh.getMatrixAt(0, shadowMatrix)
  assert.ok(shadowMatrix.elements[9] > 0.5)
  const shadow = places(shadowMesh)[0]
  const sun = resolved().sun
  const span = Math.hypot(sun[0], sun[2])
  const along = (shadow[0] - rover.position.x) * sun[0] / span + (shadow[2] - rover.position.z) * sun[2] / span
  assert.ok(along > 0.4)
  const dusk = buildMars(resolved({ timeOfDay: 'dusk' }), true)
  assert.ok(dusk.root.getObjectByName('atmos-shadow').userData.reach > shadowMesh.userData.reach)
  assert.ok(first.root.getObjectByName('atmos-phobos').position.y > dusk.root.getObjectByName('atmos-phobos').position.y)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh || obj.isPoints) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
  dusk.handle.dispose()
})

test('dust devils spin and dusk keeps the same devil count', () => {
  const built = buildMars(resolved(), true)
  const devils = built.root.getObjectByName('atmos-devil')
  const matrix = new Matrix4()
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  devils.getMatrixAt(0, matrix)
  const start = matrix.elements[0]
  built.handle.sync(2, {}, {}, 'low', 3, resolved())
  devils.getMatrixAt(0, matrix)
  assert.ok(Math.abs(matrix.elements[0] - start) > 0.2)
  const dust = built.root.getObjectByName('atmos-dust')
  assert.ok(dust.material.uniforms.uTime.value > 1)
  const moons = built.root.getObjectByName('atmos-moons')
  assert.ok(moons.rotation.y > 0.1)
  assert.equal(devils.count, 3)
  const many = buildMars(resolved({ variant: 8, palette: 'dusk' }), true)
  assert.equal(many.root.getObjectByName('atmos-devil').count, 8)
  const none = buildMars(resolved({ variant: 0 }), true)
  assert.equal(none.root.getObjectByName('atmos-devil'), undefined)
  built.handle.dispose()
  built.handle.dispose()
  many.handle.dispose()
  none.handle.dispose()
})

test('mars degrades to a flat plain without WebGL2', () => {
  const flat = buildMars(resolved(), false)
  assert.equal(flat.root.getObjectByName('atmos-phobos'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-mars-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [224, 154, 85])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
