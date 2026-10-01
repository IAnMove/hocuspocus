import assert from 'node:assert/strict'
import test from 'node:test'
import { Matrix4 } from 'three'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { buildSiliconMainframe } from '../src/features/scene3d/atmos/sets/siliconMainframe.ts'
import { cabinetLit, scanRate } from '../src/features/scene3d/atmos/sets/siliconMainframeLayout.ts'
import { atmosTemplateDocument } from '../src/features/scene3d/atmos/templates.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'
import { settingFromDressing } from '../src/features/scene3d/templateFilters.ts'

function resolved(patch = {}, quality = 'low') {
  return resolveAtmos(parseAtmosSettings({ palette: 'phosphor', timeOfDay: 'idle', variant: 4, ...patch }, 'atmos-silicon-mainframe'), quality, 'atmos-silicon-mainframe')
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

test('silicon mainframe templates keep phosphor, idle, and a six second shot', () => {
  const wide = atmosTemplateDocument('atmos-silicon-mainframe-wide')
  const low = atmosTemplateDocument('atmos-silicon-mainframe-low')
  assert.ok(wide && low)
  for (const doc of [wide, low]) {
    assert.equal(doc.dressing, 'atmos-silicon-mainframe')
    assert.equal(doc.atmos?.timeOfDay, 'idle')
    assert.equal(doc.atmos?.palette, 'phosphor')
    assert.equal(doc.atmos?.variant, 4)
    assert.deepEqual([...doc.light.direction], [0.15, -0.62, -0.77])
    assert.equal(doc.duration, 6)
    assert.equal(doc.fps, 24)
    assert.deepEqual([...doc.slots[0].position], [0.72, 0, -0.55])
    assert.equal(doc.slots[0].rotationY, 0.15)
  }
  assert.deepEqual([...wide.camera.eye], [0.35, 1.85, 4.4])
  assert.equal(wide.camera.fov, 50)
  assert.deepEqual([...low.camera.eye], [1.15, 0.42, 1.35])
  assert.equal(low.camera.fov, 58)
  assert.equal(settingFromDressing('atmos-silicon-mainframe'), 'mainframe')
  assert.equal(parseAtmosSettings({ palette: 'chrome', timeOfDay: 'burst', variant: 20 }, 'atmos-silicon-mainframe')?.variant, 8)
  assert.equal(parseAtmosSettings({ palette: 'phosphor', variant: -1 }, 'atmos-silicon-mainframe')?.variant, 0)
})

test('mainframe rows stay off the aisle and repeat', () => {
  const first = buildSiliconMainframe(resolved(), true)
  const again = buildSiliconMainframe(resolved(), true)
  const cabinets = places(first.root.getObjectByName('atmos-cabinet'))
  assert.deepEqual(cabinets, places(again.root.getObjectByName('atmos-cabinet')))
  assert.equal(cabinets.length, 8)
  assert.equal(first.root.getObjectByName('atmos-led').count, cabinets.length * 6)
  assert.equal(first.root.getObjectByName('atmos-screen').count, 3)
  for (const name of ['atmos-cabinet', 'atmos-led', 'atmos-screen', 'atmos-reel', 'atmos-drive', 'atmos-cable']) {
    for (const [x, , z] of places(first.root.getObjectByName(name))) assert.equal(outsideLane(x, z), true, `${name} ${x} ${z}`)
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

test('burst sweeps faster than idle and variant gates the cabinets', () => {
  const seed = 88023
  assert.ok(scanRate('burst') > scanRate('idle'))
  assert.equal(scanRate('burst'), 2)
  assert.equal(cabinetLit(7, 8, 0, 0.2, 'burst', seed), false)
  assert.equal(cabinetLit(7, 8, 4, 0.2, 'burst', seed), false)
  const built = buildSiliconMainframe(resolved(), true)
  built.handle.sync(0.4, {}, {}, 'low', 3, resolved())
  const again = buildSiliconMainframe(resolved(), true)
  again.handle.sync(0.4, {}, {}, 'low', 3, resolved())
  const sweep = built.root.getObjectByName('atmos-screen').material.uniforms.uSweep.value
  assert.equal(sweep, again.root.getObjectByName('atmos-screen').material.uniforms.uSweep.value)
  built.handle.sync(0.4, {}, {}, 'low', 3, resolved({ timeOfDay: 'burst' }))
  assert.ok(built.root.getObjectByName('atmos-screen').material.uniforms.uGain.value > 1)
  const high = buildSiliconMainframe(resolved({ palette: 'chrome', timeOfDay: 'burst' }, 'high'), true)
  assert.equal(high.root.getObjectByName('atmos-cabinet').count, 14)
  assert.equal(high.root.getObjectByName('atmos-mote').geometry.getAttribute('position').count, 48)
  built.handle.dispose()
  again.handle.dispose()
  high.handle.dispose()
})

test('silicon mainframe degrades to a flat floor without WebGL2', () => {
  const flat = buildSiliconMainframe(resolved(), false)
  assert.equal(flat.root.name, 'atmos-silicon-mainframe')
  assert.ok(flat.root.getObjectByName('atmos-pad'))
  assert.equal(flat.root.getObjectByName('atmos-cabinet'), undefined)
  assert.equal(flat.root.getObjectByName('atmos-screen'), undefined)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(1, {}, {}, 'low', 2)
  flat.handle.dispose()
  flat.handle.dispose()
  const scene = atmosTemplateDocument('atmos-silicon-mainframe-wide')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos, scene.dressing).sky
  assert.deepEqual([...sky], [2, 17, 10])
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
})
