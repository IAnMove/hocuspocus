import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildNeonRain } from '../src/features/scene3d/atmos/sets/neonRain.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'magenta', timeOfDay: 'night', variant: 5, ...patch }, 'atmos-neon-rain'), quality, 'atmos-neon-rain')
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

function scaleY(mesh, index = 0) {
  const matrix = new Matrix4()
  mesh.getMatrixAt(index, matrix)
  return matrix.elements[5]
}

test('neon rain templates keep magenta, night, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-neon-rain-wide')
  const low = atmosTemplateDocument('atmos-neon-rain-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-neon-rain')
    assert.equal(doc.atmos?.timeOfDay, 'night')
    assert.equal(doc.atmos?.palette, 'magenta')
    assert.equal(doc.atmos?.variant, 5)
    assert.deepEqual([...doc.light.direction], [0.1, -0.86, -0.42])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.15, 1.48, 3.9])
  assert.equal(wide.camera.fov, 50)
  assert.deepEqual([...low.camera.eye], [0.55, 0.58, 2.45])
  assert.equal(low.camera.fov, 56)
  assert.equal(settingFromDressing('atmos-neon-rain'), 'street')
  assert.equal(parseAtmosSettings({ palette: 'violet', timeOfDay: 'storm', variant: 20 }, 'atmos-neon-rain')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'magenta', variant: -1 }, 'atmos-neon-rain')?.variant, 0)
  assert.equal(parseAtmosSettings({ timeOfDay: 'noon', palette: 'violet' }, 'atmos-neon-rain')?.timeOfDay, 'night')
  assert.equal(parseAtmosSettings({ palette: 'violet' }, 'atmos-neon-rain')?.palette, 'violet')
})

test('signs, puddles, walls and steam stay off the lane', () => {
  const first = buildNeonRain(resolved(), true)
  const again = buildNeonRain(resolved(), true)
  const signs = places(first.root.getObjectByName('atmos-sign'))
  assert.deepEqual(signs.map(([x, , z]) => [x, z]), places(again.root.getObjectByName('atmos-sign')).map(([x, , z]) => [x, z]))
  assert.ok(signs.length >= 6)
  for (const name of ['atmos-sign', 'atmos-wall', 'atmos-steam']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  const puddles = first.root.getObjectByName('atmos-ground').userData.puddles
  assert.ok(puddles.length >= 4)
  for (const [x, z] of puddles) assert.equal(outsideLane(x, z), true, 'puddle')
  const ground = first.root.getObjectByName('atmos-ground').geometry.attributes.position
  let maxY = 0
  let minZ = Infinity
  let maxZ = -Infinity
  for (let i = 0; i < ground.count; i += 1) {
    maxY = Math.max(maxY, Math.abs(ground.getY(i)))
    minZ = Math.min(minZ, ground.getZ(i))
    maxZ = Math.max(maxZ, ground.getZ(i))
  }
  assert.ok(maxY < 1e-6)
  assert.ok(minZ < -1 && maxZ > 1)
  assert.equal(first.root.getObjectByName('atmos-sun'), undefined)
  assert.equal(first.root.name, 'atmos-neon-rain')
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  assert.equal(first.root.getObjectByName('atmos-rain').count, 42)
  first.handle.dispose()
  again.handle.dispose()
})

test('rain falls, steam rises, and heavier rain lengthens the streaks', () => {
  const built = buildNeonRain(resolved(), true)
  const rain = built.root.getObjectByName('atmos-rain')
  const steam = built.root.getObjectByName('atmos-steam')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const rainY = places(rain)[0][1]
  const steamY = places(steam)[0][1]
  const calmScale = scaleY(rain)
  built.handle.sync(1.2, {}, {}, 'low', 3, resolved())
  assert.ok(places(rain)[0][1] < rainY)
  assert.ok(places(steam)[0][1] > steamY)
  built.handle.sync(0, {}, {}, 'low', 3, resolved({ variant: 8 }))
  assert.ok(scaleY(rain) > calmScale)
  const calm = buildNeonRain(resolved({ variant: 0 }), true)
  calm.handle.sync(0, {}, {}, 'low', 3, resolved({ variant: 0 }))
  assert.ok(scaleY(calm.root.getObjectByName('atmos-rain')) < calmScale)
  const violet = buildNeonRain(resolved({ palette: 'violet' }), true)
  assert.ok(violet.root.getObjectByName('atmos-sign').instanceColor.getX(0) < built.root.getObjectByName('atmos-sign').instanceColor.getX(0))
  const storm = buildNeonRain(resolved({ timeOfDay: 'storm', palette: 'violet' }, 'high'), true)
  assert.equal(storm.root.getObjectByName('atmos-rain').count, 72)
  assert.equal(storm.root.getObjectByName('atmos-sun'), undefined)
  assert.ok(storm.root.getObjectByName('atmos-steam'))
  built.handle.dispose()
  built.handle.dispose()
  calm.handle.dispose()
  violet.handle.dispose()
  storm.handle.dispose()
})

test('neon rain degrades to a flat floor without WebGL2', () => {
  const flat = buildNeonRain(resolved(), false)
  assert.equal(flat.root.name, 'atmos-neon-rain')
  assert.equal(flat.root.getObjectByName('atmos-sign'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-rain'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-steam'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-neon-rain-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [42, 18, 56])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
