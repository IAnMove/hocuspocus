import assert from 'node:assert/strict'
import test from 'node:test'
import { Color, Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildMeadow } from '../src/features/scene3d/atmos/sets/meadow.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'clover', timeOfDay: 'spring', variant: 4, ...patch }, 'atmos-meadow'), quality, 'atmos-meadow')
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

function near(color, hex) {
  const expected = new Color(hex)
  return Math.abs(color.r - expected.r) < 0.01 && Math.abs(color.g - expected.g) < 0.01 && Math.abs(color.b - expected.b) < 0.01
}

test('meadow templates keep clover, spring, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-meadow-wide')
  const low = atmosTemplateDocument('atmos-meadow-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-meadow')
    assert.equal(doc.atmos?.timeOfDay, 'spring')
    assert.equal(doc.atmos?.palette, 'clover')
    assert.equal(doc.atmos?.variant, 4)
    assert.deepEqual([...doc.light.direction], [0.38, -0.74, -0.5])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.1, 1.7, 6.2])
  assert.equal(wide.camera.fov, 50)
  assert.deepEqual([...low.camera.eye], [1.05, 0.48, 5.8])
  assert.equal(low.camera.fov, 56)
  assert.equal(settingFromDressing('atmos-meadow'), 'forest')
  assert.equal(parseAtmosSettings({ palette: 'clover', timeOfDay: 'overcast', variant: 20 }, 'atmos-meadow')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'hay', variant: -1 }, 'atmos-meadow')?.variant, 0)
  assert.equal(parseAtmosSettings({ timeOfDay: 'noon' }, 'atmos-meadow')?.timeOfDay, 'spring')
})

test('grass stays off the lane and low clouds sit above the figure', () => {
  const first = buildMeadow(resolved(), true)
  const again = buildMeadow(resolved(), true)
  const grass = places(first.root.getObjectByName('atmos-grass'))
  const clouds = places(first.root.getObjectByName('atmos-cloud'))
  assert.deepEqual(grass, places(again.root.getObjectByName('atmos-grass')))
  assert.equal(grass.length, 200)
  assert.equal(clouds.length, 8)
  for (const [x, y, z] of grass) {
    assert.equal(outsideLane(x, z), true)
    assert.ok(Math.abs(y) < 0.001)
  }
  for (const [, y] of clouds) assert.ok(y > 2.2)
  assert.equal(first.root.name, 'atmos-meadow')
  assert.equal(first.root.getObjectByName('atmos-sun'), undefined)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 150)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('breeze bends the grass and low clouds drift', () => {
  const built = buildMeadow(resolved(), true)
  const grass = built.root.getObjectByName('atmos-grass')
  const clouds = built.root.getObjectByName('atmos-cloud')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const bend = grass.material.uniforms.uBend.value
  const parked = places(clouds)[0][0]
  const planted = places(grass)
  built.handle.sync(2, {}, {}, 'low', 3, resolved({ variant: 8 }))
  assert.equal(grass.material.uniforms.uTime.value, 2)
  assert.ok(grass.material.uniforms.uBend.value > bend)
  assert.deepEqual(places(grass), planted)
  assert.notEqual(places(clouds)[0][0], parked)
  const calm = buildMeadow(resolved({ variant: 0 }), true)
  assert.ok(calm.root.getObjectByName('atmos-grass').material.uniforms.uBend.value < bend)
  const hay = buildMeadow(resolved({ timeOfDay: 'overcast', palette: 'hay' }, 'high'), true)
  assert.equal(hay.root.getObjectByName('atmos-grass').count, 280)
  assert.equal(hay.root.getObjectByName('atmos-cloud').count, 12)
  assert.equal(near(hay.root.getObjectByName('atmos-sky').material.uniforms.uZenith.value, '#a39e94'), true)
  assert.equal(hay.root.getObjectByName('atmos-sun'), undefined)
  built.handle.dispose()
  built.handle.dispose()
  calm.handle.dispose()
  hay.handle.dispose()
})

test('meadow degrades to a flat floor without WebGL2', () => {
  const flat = buildMeadow(resolved(), false)
  assert.equal(flat.root.name, 'atmos-meadow')
  assert.equal(flat.root.getObjectByName('atmos-grass'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-cloud'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-meadow-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [191, 227, 246])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
