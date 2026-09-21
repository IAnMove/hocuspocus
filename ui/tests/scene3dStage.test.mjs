import assert from 'node:assert/strict'
import test from 'node:test'
import { cylinderUvOffset } from '../src/features/scene3d/backdrop.ts'
import { cameraEyeAtTime, cameraLookAtTime, orbitEye } from '../src/features/scene3d/camera.ts'
import { clipBindingError, resolveScene3DClip } from '../src/features/scene3d/clips.ts'
import { scene3dClipLocalTime, scene3dFrameCount, scene3dFrameTime } from '../src/features/scene3d/clock.ts'
import { cloneScene3DDocument, createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { applyScene3DTemplate, patchScene3DSlot } from '../src/features/scene3d/templates.ts'
import { documentFromWorld3DRequest } from '../src/features/scene3d/world3dAgent.ts'
import { canMutateWorld3DScene, finishWorld3DExport, paintWorld3DExportFrame, startWorld3DExport } from '../src/features/scene3d/exportLock.ts'
import { evenDim, world3dEncoderConfig, world3dExportPlan, world3dExportSize } from '../src/features/scene3d/exportMp4.ts'
import { world3dRecordingStub } from '../src/features/scene3d/publish.ts'
import { hashSoftwareFrame, renderScene3DSoftware } from '../src/features/scene3d/softwareRender.ts'

test('frame clock matches compositor export indexing', () => {
  assert.equal(scene3dFrameCount(2, 30), 60)
  assert.equal(scene3dFrameTime(0, 2, 30), 0)
  assert.equal(scene3dFrameTime(59, 2, 30), 59 / 30)
  assert.ok(scene3dFrameTime(59, 2, 30) < 2)
})

test('unknown clip duration is not treated as zero playback', () => {
  assert.equal(scene3dClipLocalTime(1.2, null), null)
  assert.equal(scene3dClipLocalTime(1.2, 0), null)
  assert.equal(scene3dClipLocalTime(0.5, 1, { loop: true }), 0.5)
})

test('clip identity is index plus exact name', () => {
  const catalog = [
    { index: 0, name: 'Armature|clip0|baselayer', durationSeconds: 0.033 },
    { index: 1, name: 'Running', durationSeconds: 0.667 },
  ]
  const running = resolveScene3DClip(catalog, { index: 1, name: 'Running' })
  assert.equal(running && 'name' in running && running.name, 'Running')
  const missing = clipBindingError(resolveScene3DClip(catalog, { index: 9, name: 'Running' }))
  assert.equal(missing?.code, 'clip_missing')
  const mismatch = clipBindingError(resolveScene3DClip(catalog, { index: 1, name: 'run' }))
  assert.equal(mismatch?.code, 'clip_name_mismatch')
})

test('clip catalogs are per slot, not a shared name list', () => {
  const subject = [
    { index: 0, name: 'Armature|clip0|baselayer', durationSeconds: 0.033 },
    { index: 1, name: 'Running', durationSeconds: 0.667 },
  ]
  const prop = [{ index: 0, name: 'Spin', durationSeconds: 2 }]
  assert.equal(clipBindingError(resolveScene3DClip(subject, { index: 1, name: 'Running' })), null)
  assert.equal(clipBindingError(resolveScene3DClip(prop, { index: 1, name: 'Running' }))?.code, 'clip_missing')
})

test('save and reopen keeps camera, light, slots and clip refs', () => {
  const original = createDefaultScene3DDocument()
  original.slots[0].clip = { index: 1, name: 'Running' }
  original.camera.family = 'orbit'
  const restored = parseScene3DDocument(JSON.parse(JSON.stringify(cloneScene3DDocument(original))))
  assert.ok(restored)
  assert.equal(restored.camera.family, 'orbit')
  assert.deepEqual(restored.slots[0].clip, { index: 1, name: 'Running' })
  assert.equal(restored.light.kind, 'directional')
  assert.equal(restored.slots.length, 2)
})

test('software frames differ when subjects move or the camera orbits', () => {
  const document = createDefaultScene3DDocument()
  const first = hashSoftwareFrame(renderScene3DSoftware(document, 0))
  document.slots[0].position = [1.4, 0, 0]
  const moved = hashSoftwareFrame(renderScene3DSoftware(document, 0))
  assert.notEqual(first, moved)
  const orbitDoc = createDefaultScene3DDocument()
  orbitDoc.camera.family = 'orbit'
  const a = hashSoftwareFrame(renderScene3DSoftware(orbitDoc, 0))
  const b = hashSoftwareFrame(renderScene3DSoftware(orbitDoc, 2))
  assert.notEqual(a, b)
  const eye0 = cameraEyeAtTime(orbitDoc.camera, 0, 4)
  const eyeHalf = orbitEye(orbitDoc.camera.look, 4.2, 1.6, Math.PI)
  assert.notEqual(eye0[0], eyeHalf[0])
})

test('cinematic templates bind slots and a camera family', () => {
  const two = applyScene3DTemplate('two-shot')
  assert.equal(two.templateId, 'two-shot')
  assert.equal(two.camera.family, 'establishment')
  assert.deepEqual(two.slots.map(slot => slot.slot), ['subject_1', 'subject_2', 'background'])
  const product = applyScene3DTemplate('product-orbit')
  assert.equal(product.camera.family, 'product')
  const moved = patchScene3DSlot(two, 'subject_1', { position: [2, 0, 0], scale: 1.4 })
  assert.equal(moved.slots[0].position[0], 2)
  assert.equal(moved.slots[0].scale, 1.4)
})

test('wizard mount request uses the same template ids as the editor', () => {
  const document = documentFromWorld3DRequest({
    type: 'mount_world3d_template',
    templateId: 'over-shoulder',
    bindings: { subject_1: { url: '/api/v1/file/hero.glb', media: 'model3d' } },
  })
  assert.equal(document.templateId, 'over-shoulder')
  assert.equal(document.camera.family, 'encounter')
  assert.equal(document.slots[0].sourceUrl, '/api/v1/file/hero.glb')
})

test('establishment camera eases in rather than sitting still', () => {
  const document = applyScene3DTemplate('hero-push')
  const a = cameraEyeAtTime(document.camera, 0, document.duration, document.slots)
  const b = cameraEyeAtTime(document.camera, document.duration, document.duration, document.slots)
  assert.notEqual(a[2], b[2])
})

test('run-loop keeps the subject still and scrolls the cylinder world', () => {
  const document = applyScene3DTemplate('run-loop')
  assert.equal(document.templateId, 'run-loop')
  assert.equal(document.camera.family, 'side')
  assert.equal(document.dressing, 'treadmill')
  const subject = document.slots.find(slot => slot.slot === 'subject_1')
  const background = document.slots.find(slot => slot.slot === 'background')
  assert.ok(subject)
  assert.ok(background)
  assert.deepEqual(subject.position, [0, 0, 0])
  assert.equal(background.media, 'image')
  assert.equal(background.loop?.cylinder, true)
  assert.ok((background.loop?.speed ?? 0) < 0)
  assert.equal(subject.clip, null)
  const restored = parseScene3DDocument(JSON.parse(JSON.stringify(document)))
  assert.equal(restored?.slots.find(slot => slot.slot === 'background')?.loop?.cylinder, true)
  assert.equal(restored?.dressing, 'treadmill')
  const still = hashSoftwareFrame(renderScene3DSoftware(document, 0))
  const later = hashSoftwareFrame(renderScene3DSoftware(document, 1.5))
  assert.notEqual(still, later)
  assert.deepEqual(document.slots[0].position, [0, 0, 0])
  const look = cameraLookAtTime(document.camera, 1, document.duration, document.slots)
  const eye = cameraEyeAtTime(document.camera, 1, document.duration, document.slots)
  assert.equal(look[0], subject.position[0])
  assert.ok(eye[2] > look[2])
  assert.ok(Math.abs(eye[1] - look[1]) < 0.25)
  assert.notEqual(cylinderUvOffset(0, -0.18), cylinderUvOffset(1, -0.18))
})

test('music-video templates keep clips unbound and dress the world', () => {
  const space = applyScene3DTemplate('space-float')
  assert.equal(space.dressing, 'space')
  assert.equal(space.camera.family, 'musical')
  assert.equal(space.slots[0].clip, null)
  assert.ok((space.slots.find(slot => slot.slot === 'background')?.loop?.cylinder))
  const street = applyScene3DTemplate('block-street')
  assert.equal(street.dressing, 'treadmill')
  assert.equal(street.camera.family, 'side')
  const dance = applyScene3DTemplate('dance-orbit')
  assert.equal(dance.camera.family, 'orbit')
  assert.equal(dance.slots[0].clip, null)
})

test('cafe-dance is a front set with a textured building, not a cylinder', () => {
  const document = applyScene3DTemplate('cafe-dance')
  assert.equal(document.templateId, 'cafe-dance')
  assert.equal(document.dressing, 'cafe')
  assert.equal(document.camera.family, 'front')
  assert.equal(document.camera.fov, 42)
  assert.equal(document.slots[0].clip, null)
  assert.equal(document.slots[0].rotationY, 0)
  assert.equal(document.slots.some(slot => slot.slot === 'background'), false)
  const look = cameraLookAtTime(document.camera, 1, document.duration, document.slots)
  const eye = cameraEyeAtTime(document.camera, 1, document.duration, document.slots)
  assert.ok(eye[2] > look[2])
  assert.ok(Math.abs(eye[1] - look[1]) < 0.2)
  const restored = parseScene3DDocument(JSON.parse(JSON.stringify(document)))
  assert.equal(restored?.dressing, 'cafe')
})

test('drive templates keep the car still and scroll the world', () => {
  const chase = applyScene3DTemplate('drive-chase')
  assert.equal(chase.dressing, 'drive-city')
  assert.equal(chase.camera.family, 'chase')
  const background = chase.slots.find(slot => slot.slot === 'background')
  assert.equal(background?.loop?.cylinder, true)
  assert.ok((background?.loop?.speed ?? 0) > 0)
  assert.equal(background?.sourceUrl, '/scene3d/drive-city.jpg')
  const eye = cameraEyeAtTime(chase.camera, 1, chase.duration, chase.slots)
  const look = cameraLookAtTime(chase.camera, 1, chase.duration, chase.slots)
  assert.ok(eye[2] > look[2])
  const hood = applyScene3DTemplate('drive-hood')
  assert.equal(hood.camera.family, 'hood')
  const wing = applyScene3DTemplate('drive-wing')
  assert.equal(wing.dressing, 'drive-coast')
  assert.equal(wing.camera.family, 'wing')
  const tunnel = applyScene3DTemplate('drive-tunnel')
  assert.equal(tunnel.dressing, 'drive-tunnel')
  const hero = applyScene3DTemplate('drive-hero')
  assert.equal(hero.slots[0].clip, null)
  assert.ok(hero.slots[0].scale < 1)
  const restored = parseScene3DDocument(JSON.parse(JSON.stringify(chase)))
  assert.equal(restored?.dressing, 'drive-city')
})

test('world3d export plan is independent of compositor layers', () => {
  assert.equal(evenDim(1281), 1280)
  assert.deepEqual(world3dExportSize(1920, 1080), { width: 1920, height: 1080 })
  const plan = world3dExportPlan(2, 30)
  assert.equal(plan.count, 60)
  assert.equal(plan.times[0], 0)
  assert.ok(plan.times[59] < 2)
  const document = applyScene3DTemplate('run-loop')
  const stub = world3dRecordingStub(document)
  assert.equal(stub.version, 1)
  assert.equal(stub.name, 'world3d-run-loop')
  assert.deepEqual(stub.layers, [])
  assert.equal(stub.fps, 30)
})

test('full HD export and publication retain orientation without upscaling smaller shots', () => {
  for (const [width, height, expected] of [
    [1920, 1080, { width: 1920, height: 1080 }],
    [1080, 1920, { width: 1080, height: 1920 }],
    [1280, 720, { width: 1280, height: 720 }],
    [720, 1280, { width: 720, height: 1280 }],
    [3840, 2160, { width: 1920, height: 1080 }],
    [2160, 3840, { width: 1080, height: 1920 }],
    [2160, 2160, { width: 1080, height: 1080 }],
    [641, 481, { width: 640, height: 480 }],
  ]) {
    assert.deepEqual(world3dExportSize(width, height), expected)
    const stub = world3dRecordingStub({ ...applyScene3DTemplate('run-loop'), width, height })
    assert.deepEqual({ width: stub.width, height: stub.height }, expected)
  }
})

test('encoder level admits full HD at 60 fps while preserving the 720p configuration', () => {
  assert.equal(world3dEncoderConfig(1280, 720, 60).codec, 'avc1.640028')
  assert.equal(world3dEncoderConfig(1920, 1080, 30).codec, 'avc1.640028')
  for (const [width, height] of [[1920, 1080], [1080, 1920], [1080, 1080]]) {
    const config = world3dEncoderConfig(width, height, 60)
    assert.equal(config.codec, 'avc1.64002a')
    assert.equal(config.width, width)
    assert.equal(config.height, height)
    assert.equal(config.framerate, 60)
    assert.ok(config.bitrate <= 24_000_000)
  }
})

test('wizard can mount the run-loop cylinder template', () => {
  const document = documentFromWorld3DRequest({
    type: 'mount_world3d_template',
    templateId: 'run-loop',
    bindings: {
      subject_1: { url: '/api/v1/file/hero.glb', media: 'model3d' },
      background: { url: '/api/v1/file/street.png', media: 'image' },
    },
  })
  assert.equal(document.templateId, 'run-loop')
  assert.equal(document.camera.family, 'side')
  assert.equal(document.slots[0].sourceUrl, '/api/v1/file/hero.glb')
  assert.equal(document.slots[0].clip, null)
  const background = document.slots.find(slot => slot.slot === 'background')
  assert.equal(background?.sourceUrl, '/api/v1/file/street.png')
  assert.equal(background?.loop?.cylinder, true)
})

test('world3d export paints and publishes the snapshot after the live scene changes', () => {
  const snapshot = applyScene3DTemplate('drive-chase')
  const live = { current: snapshot }
  const painted = []
  const calls = []
  let pinned = null
  const handle = {
    paint(_seconds, document) {
      painted.push((document ?? live.current).templateId)
      return { tagName: 'CANVAS' }
    },
    beginExport(document) {
      pinned = document
      calls.push('beginExport')
    },
    endExport() { calls.push('endExport') },
    setExportSize() { calls.push('setExportSize') },
    setExportQuality(enabled) { calls.push(enabled ? 'exportQualityOn' : 'exportQualityOff') },
    restoreSize() { calls.push('restoreSize') },
  }
  const frozen = startWorld3DExport(handle, snapshot, { width: 1280, height: 720 })
  assert.notEqual(frozen, snapshot)
  assert.equal(pinned, frozen)
  live.current = applyScene3DTemplate('cafe-dance')
  frozen.camera.family = 'hood'
  assert.equal(snapshot.camera.family, 'chase')
  assert.equal(canMutateWorld3DScene(true), false)
  assert.equal(canMutateWorld3DScene(false), true)
  const frame = paintWorld3DExportFrame(handle, frozen, 0.5)
  assert.equal(frame.tagName, 'CANVAS')
  assert.deepEqual(painted, ['drive-chase'])
  finishWorld3DExport(handle)
  assert.deepEqual(calls, ['beginExport', 'setExportSize', 'exportQualityOn', 'exportQualityOff', 'endExport', 'restoreSize'])
})

test('world3d export paint fails closed when the stage is gone', () => {
  assert.throws(
    () => paintWorld3DExportFrame({ paint: () => null }, applyScene3DTemplate('drive-chase'), 0),
    /stage|listo|ready/i,
  )
})
