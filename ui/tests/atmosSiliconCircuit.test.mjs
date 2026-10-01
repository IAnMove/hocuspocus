import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildSiliconCircuit } from '../src/features/scene3d/atmos/sets/siliconCircuit.ts'
import { ledLit, pulseRate, worldOffset } from '../src/features/scene3d/atmos/sets/siliconCircuitLayout.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'phosphor', timeOfDay: 'idle', variant: 4, ...patch }, 'atmos-silicon-circuit'), quality, 'atmos-silicon-circuit')
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

test('silicon circuit templates keep phosphor, idle, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-silicon-circuit-wide')
  const low = atmosTemplateDocument('atmos-silicon-circuit-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-silicon-circuit')
    assert.equal(doc.atmos?.timeOfDay, 'idle')
    assert.equal(doc.atmos?.palette, 'phosphor')
    assert.equal(doc.atmos?.variant, 4)
    assert.deepEqual([...doc.light.direction], [0.2, -0.55, -0.8])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.25, 2.15, 4.6])
  assert.equal(wide.camera.fov, 50)
  assert.deepEqual([...low.camera.eye], [1.2, 0.18, 0.85])
  assert.equal(low.camera.fov, 62)
  assert.equal(settingFromDressing('atmos-silicon-circuit'), 'circuit')
  assert.equal(parseAtmosSettings({ palette: 'phosphor', timeOfDay: 'compute', variant: 20 }, 'atmos-silicon-circuit')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'outrun', variant: -1 }, 'atmos-silicon-circuit')?.variant, 0)
})

test('circuit parts stay off the lane and repeat', () => {
  const first = buildSiliconCircuit(resolved(), true)
  const again = buildSiliconCircuit(resolved(), true)
  const chips = places(first.root.getObjectByName('atmos-chip'))
  assert.deepEqual(chips, places(again.root.getObjectByName('atmos-chip')))
  assert.ok(chips.length >= 4)
  assert.equal(first.root.getObjectByName('atmos-chip').isInstancedMesh, true)
  assert.equal(first.root.getObjectByName('atmos-pin').count, chips.length * 4)
  for (const name of ['atmos-chip', 'atmos-pin', 'atmos-dot', 'atmos-cap', 'atmos-bridge', 'atmos-fin']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, name)
  }
  const pad = first.root.getObjectByName('atmos-pad')
  assert.equal(pad.position.x, CLEARING_SUBJECT[0])
  assert.equal(pad.position.z, CLEARING_SUBJECT[2])
  let draws = 0
  first.root.traverse(obj => { if (obj.isMesh || obj.isPoints) draws += 1 })
  assert.ok(draws < 20)
  assert.deepEqual(first.handle.passes(), [])
  first.handle.dispose()
  again.handle.dispose()
})

test('compute pulses faster than idle and variant gates the lamps', () => {
  const quarter = worldOffset(Math.PI / 2, 1, 0)
  assert.ok(Math.abs(quarter[0]) < 1e-9)
  assert.ok(Math.abs(quarter[1] + 1) < 1e-9)
  assert.deepEqual(worldOffset(0, 1, 0), [1, 0])
  assert.ok(pulseRate('compute') > pulseRate('idle'))
  assert.equal(pulseRate('compute'), 2)
  const seed = 88022
  assert.equal(ledLit(7, 8, 0, 0.2, 'compute', seed), false)
  assert.equal(ledLit(7, 8, 4, 0.2, 'compute', seed), false)
  assert.equal(ledLit(0, 8, 8, 0.2, 'compute', seed), ledLit(0, 8, 8, 0.2, 'compute', seed))
  const built = buildSiliconCircuit(resolved(), true)
  built.handle.sync(0.2, {}, {}, 'low', 3, resolved())
  const again = buildSiliconCircuit(resolved(), true)
  again.handle.sync(0.2, {}, {}, 'low', 3, resolved())
  const sweep = built.root.getObjectByName('atmos-board').material.uniforms.uSweep.value
  assert.equal(sweep, again.root.getObjectByName('atmos-board').material.uniforms.uSweep.value)
  built.handle.sync(0.2, {}, {}, 'low', 3, resolved({ timeOfDay: 'compute' }))
  assert.ok(built.root.getObjectByName('atmos-board').material.uniforms.uGain.value > 1)
  const high = buildSiliconCircuit(resolved({ palette: 'outrun', timeOfDay: 'compute' }, 'high'), true)
  assert.equal(high.root.getObjectByName('atmos-chip').count, 14)
  assert.equal(high.root.getObjectByName('atmos-mote').geometry.getAttribute('position').count, 32)
  built.handle.dispose()
  again.handle.dispose()
  high.handle.dispose()
})

test('silicon circuit degrades to a flat board without WebGL2', () => {
  const flat = buildSiliconCircuit(resolved(), false)
  assert.equal(flat.root.name, 'atmos-silicon-circuit')
  assert.ok(flat.root.getObjectByName('atmos-pad'))
  assert.equal(flat.root.getObjectByName('atmos-board'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-chip'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-silicon-circuit-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [2, 17, 10])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
