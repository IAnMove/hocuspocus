import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildReef } from '../src/features/scene3d/atmos/sets/reef.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'lagoon', timeOfDay: 'shallows', variant: 4, ...patch }, 'atmos-reef'), quality, 'atmos-reef')
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

test('reef templates keep lagoon, shallows, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-reef-wide')
  const low = atmosTemplateDocument('atmos-reef-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-reef')
    assert.equal(doc.atmos?.timeOfDay, 'shallows')
    assert.equal(doc.atmos?.palette, 'lagoon')
    assert.equal(doc.atmos?.variant, 4)
    assert.deepEqual([...doc.light.direction], [0.18, -0.9, -0.38])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.15, 1.48, 3.9])
  assert.equal(wide.camera.fov, 50)
  assert.deepEqual([...low.camera.eye], [0.55, 0.62, 2.35])
  assert.equal(low.camera.fov, 56)
  assert.equal(settingFromDressing('atmos-reef'), 'sea')
  assert.equal(parseAtmosSettings({ palette: 'lagoon', timeOfDay: 'trench', variant: 20 }, 'atmos-reef')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'abyss', variant: -1 }, 'atmos-reef')?.variant, 0)
  assert.equal(parseAtmosSettings({ palette: 'nope' }, 'atmos-reef')?.palette, 'lagoon')
})

test('fish and rocks stay off the open sand', () => {
  const first = buildReef(resolved(), true)
  const again = buildReef(resolved(), true)
  const fish = places(first.root.getObjectByName('atmos-fish'))
  assert.deepEqual(fish, places(again.root.getObjectByName('atmos-fish')))
  assert.ok(fish.length >= 6)
  for (const name of ['atmos-fish', 'atmos-rock', 'atmos-coral', 'atmos-bubble']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  const ground = first.root.getObjectByName('atmos-ground')
  const normal = ground.geometry.getAttribute('normal')
  let facing = 0
  for (let i = 0; i < normal.count; i += 1) if (normal.getY(i) > 0.5) facing += 1
  assert.equal(facing, normal.count)
  assert.equal(ground.material.type, 'ShaderMaterial')
  assert.equal(ground.material.uniforms.uCurrent.value, 4)
  assert.equal(first.root.getObjectByName('atmos-fish').material.type, 'MeshBasicMaterial')
  assert.equal(first.root.getObjectByName('atmos-fish').isInstancedMesh, true)
  assert.equal(first.root.getObjectByName('atmos-bubble').isInstancedMesh, true)
  assert.equal(first.root.getObjectByName('atmos-sun'), undefined)
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('the current moves the school and bubbles rise', () => {
  const built = buildReef(resolved(), true)
  const fish = built.root.getObjectByName('atmos-fish')
  const bubbles = built.root.getObjectByName('atmos-bubble')
  const ground = built.root.getObjectByName('atmos-ground')
  built.handle.sync(0, {}, {}, 'low', 3, resolved())
  const parked = places(fish)[0][0]
  const bubbleY = places(bubbles)[0][1]
  built.handle.sync(2, {}, {}, 'low', 3, resolved({ variant: 8 }))
  assert.notEqual(places(fish)[0][0], parked)
  assert.notEqual(places(bubbles)[0][1], bubbleY)
  assert.ok(ground.material.uniforms.uTime.value > 1)
  assert.equal(ground.material.uniforms.uCurrent.value, 8)
  const calm = buildReef(resolved({ variant: 0 }), true)
  assert.equal(calm.root.getObjectByName('atmos-ground').material.uniforms.uCurrent.value, 0)
  assert.ok(calm.root.getObjectByName('atmos-bubble'))
  const trench = buildReef(resolved({ timeOfDay: 'trench', palette: 'abyss' }, 'high'), true)
  assert.equal(trench.root.getObjectByName('atmos-fish').count, 16)
  assert.equal(trench.root.getObjectByName('atmos-bubble').count, 18)
  assert.equal(trench.root.getObjectByName('atmos-ground').material.uniforms.uGain.value, 0.42)
  assert.equal(trench.root.getObjectByName('atmos-sun'), undefined)
  built.handle.dispose()
  built.handle.dispose()
  calm.handle.dispose()
  trench.handle.dispose()
})

test('reef degrades to a flat sand floor without WebGL2', () => {
  const flat = buildReef(resolved(), false)
  assert.equal(flat.root.name, 'atmos-reef')
  assert.equal(flat.root.getObjectByName('atmos-reef')?.name, 'atmos-reef')
  assert.equal(flat.root.getObjectByName('atmos-fish'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-bubble'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-reef-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [20, 120, 136])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
