import assert from 'node:assert/strict'
import test from 'node:test'
import { atmosEye } from '../src/features/scene3d/atmos/eye.ts'
import { atmosFallbackLook } from '../src/features/scene3d/atmos/degrade.ts'
import { clearingTrunks, scatter, subjectIsClear, CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { atmosFingerprint, parseAtmosSettings, resolveAtmos } from '../src/features/scene3d/atmos/params.ts'
import { windAt } from '../src/features/scene3d/atmos/wind.ts'
import { buildClearing } from '../src/features/scene3d/atmos/sets/clearing.ts'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'
import { cameraEyeAtTime } from '../src/features/scene3d/camera.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'

test('clearing wind, trunks and fingerprint stay put for the same second', () => {
  const resolved = resolveAtmos(parseAtmosSettings({}), 'low')
  assert.deepEqual(windAt(1.2, -3, 4, 0.4, 0.2, resolved.seed), windAt(1.2, -3, 4, 0.4, 0.2, resolved.seed))
  const trunks = clearingTrunks(resolved.seed)
  assert.deepEqual(trunks, clearingTrunks(resolved.seed))
  assert.equal(subjectIsClear(trunks), true)
  for (const trunk of trunks) {
    const dx = trunk.x - CLEARING_SUBJECT[0]
    const dz = trunk.z - CLEARING_SUBJECT[2]
    assert.ok(dx * dx + dz * dz >= 1.4 * 1.4)
    const inLane = trunk.z > -1.15 && trunk.z < 3.5 && trunk.x > -1.05 && trunk.x < 1.7
    assert.equal(inLane, false)
  }
  assert.equal(atmosFingerprint(resolved, 4), atmosFingerprint(resolveAtmos(parseAtmosSettings({}), 'low'), 4))
})

test('clearing degrades without WebGL2 and dispose is safe twice', () => {
  const resolved = resolveAtmos(undefined, 'low')
  const flat = buildClearing(resolved, false)
  assert.deepEqual(flat.handle.passes(), [])
  flat.handle.sync(0, {}, {}, 'low', 3.4)
  flat.handle.dispose()
  flat.handle.dispose()
  const full = buildClearing(resolved, true)
  assert.equal(full.handle.passes().length, 3)
  const ground = full.root.getObjectByName('atmos-ground')
  const normal = ground.geometry.getAttribute('normal')
  let up = 0
  for (let i = 0; i < normal.count; i += 1) if (normal.getY(i) > 0) up += 1
  assert.ok(up > normal.count * 0.9)
  full.handle.dispose()
  full.handle.dispose()
})

test('clearing camera stays at eye height while the dolly moves', () => {
  const scene = applyScene3DTemplate('atmos-clearing-wide')
  const start = atmosEye(cameraEyeAtTime(scene.camera, 0, scene.duration, scene.slots), 0, scene.duration, 'establishment')
  const end = atmosEye(cameraEyeAtTime(scene.camera, scene.duration, scene.duration, scene.slots), scene.duration, scene.duration, 'establishment')
  assert.ok(Math.abs(start[2] - end[2]) > 0.5)
  assert.ok(Math.abs(start[1] - scene.camera.eye[1]) < 0.05)
  assert.ok(Math.abs(end[1] - scene.camera.eye[1]) < 0.05)
  const round = parseScene3DDocument(JSON.parse(JSON.stringify(scene)))
  assert.equal(round?.dressing, 'atmos-clearing')
  assert.equal(round?.atmos?.timeOfDay, 'golden')
  const frame = renderScene3DSoftware(scene, 0)
  const sky = atmosFallbackLook(scene.atmos).sky
  assert.equal(frame.pixels[0], sky[0])
  assert.equal(frame.pixels[1], sky[1])
  assert.equal(frame.pixels[2], sky[2])
  assert.notEqual(sky[0], 18)
})

test('understory props stay out of the lane, the subject and every trunk', () => {
  const resolved = resolveAtmos(parseAtmosSettings({}), 'low')
  const trunks = clearingTrunks(resolved.seed)
  const area = { x0: -10, x1: 10, z0: 3, z1: -15 }
  const spots = scatter(40, resolved.seed, 71, trunks, area, 0.4)
  assert.deepEqual(spots, scatter(40, resolved.seed, 71, trunks, area, 0.4))
  assert.ok(spots.length >= 30)
  for (const [x, z] of spots) {
    assert.equal(z > -1.15 && z < 3.5 && x > -1.05 && x < 1.7, false)
    assert.ok((x - CLEARING_SUBJECT[0]) ** 2 + (z - CLEARING_SUBJECT[2]) ** 2 >= 1.4 * 1.4)
    for (const trunk of trunks) assert.ok((trunk.x - x) ** 2 + (trunk.z - z) ** 2 >= (trunk.radius + 0.4) ** 2)
  }
})
