import assert from 'node:assert/strict'
import test from 'node:test'
import { cameraEyeAtTime, cameraLookAtTime, projectPoint } from '../src/features/scene3d/camera.ts'
import {
  applyFrameFormat,
  fromPortraitCamera,
  scene3dFrameFormat,
  toPortraitCamera,
} from '../src/features/scene3d/frameFormat.ts'
import { throwIfAborted, world3dExportPlan } from '../src/features/scene3d/exportMp4.ts'
import { world3dRecordingStub } from '../src/features/scene3d/publish.ts'
import { applyScene3DTemplate, remountScene3DTemplate, SCENE3D_TEMPLATES } from '../src/features/scene3d/templates.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { canonicalSceneFps } from '../src/lib/sceneFps.ts'

test('canonical fps keeps 24, 30 and 60', () => {
  assert.equal(canonicalSceneFps(24), 24)
  assert.equal(canonicalSceneFps(30), 30)
  assert.equal(canonicalSceneFps(60), 60)
  assert.equal(canonicalSceneFps(25), 30)
  assert.equal(world3dExportPlan(2, 24).count, 48)
  assert.equal(world3dRecordingStub({ ...applyScene3DTemplate('two-shot'), fps: 24 }).fps, 24)
})

test('portrait cameras invert back to the authored landscape shot', () => {
  const landscape = applyScene3DTemplate('two-shot')
  const portrait = applyFrameFormat(landscape, 'portrait')
  assert.equal(scene3dFrameFormat(portrait.width, portrait.height), 'portrait')
  assert.equal(portrait.camera.frameFormat, 'portrait')
  assert.notEqual(portrait.camera.fov, landscape.camera.fov)
  const restored = applyFrameFormat(portrait, 'landscape')
  assert.equal(restored.width, 1280)
  assert.equal(restored.height, 720)
  assert.equal(restored.camera.frameFormat, undefined)
  assert.ok(Math.abs(restored.camera.fov - landscape.camera.fov) < 1e-9)
  assert.ok(restored.camera.eye.every((value, index) => Math.abs(value - landscape.camera.eye[index]) < 1e-9))
  assert.deepEqual(fromPortraitCamera(toPortraitCamera(landscape.camera)).eye, landscape.camera.eye)
})

test('every 3D shot has a mobile camera that still looks at the scene', () => {
  for (const template of SCENE3D_TEMPLATES) {
    const scene = applyFrameFormat(applyScene3DTemplate(template.id), 'portrait')
    assert.equal(parseScene3DDocument(JSON.parse(JSON.stringify(scene)))?.camera.frameFormat, 'portrait', template.id)
    for (const phase of [0, 0.5, 1]) {
      const eye = cameraEyeAtTime(scene.camera, phase * scene.duration, scene.duration, scene.slots)
      const look = cameraLookAtTime(scene.camera, phase * scene.duration, scene.duration, scene.slots)
      assert.ok([...eye, ...look].every(Number.isFinite), template.id)
      assert.ok(Math.hypot(...eye.map((value, index) => value - look[index])) > 0.2, template.id)
      const projected = projectPoint(look, eye, look, scene.camera.fov, 9 / 16)
      assert.ok(projected, template.id)
      assert.ok(projected.x > 0.05 && projected.x < 0.95, `${template.id} look x ${projected.x}`)
      assert.ok(projected.y > 0.05 && projected.y < 0.95, `${template.id} look y ${projected.y}`)
    }
  }
})

test('remounting a template keeps the mobile frame and adapts the new camera', () => {
  const portrait = applyFrameFormat(applyScene3DTemplate('two-shot'), 'portrait')
  const next = remountScene3DTemplate('over-shoulder', portrait)
  assert.equal(next.width, 720)
  assert.equal(next.height, 1280)
  assert.equal(next.camera.frameFormat, 'portrait')
  assert.equal(next.templateId, 'over-shoulder')
  const authored = applyScene3DTemplate('over-shoulder')
  assert.notEqual(next.camera.fov, authored.camera.fov)
})

test('throwIfAborted surfaces a cancel as AbortError', () => {
  throwIfAborted()
  throwIfAborted(new AbortController().signal)
  const abort = new AbortController()
  abort.abort()
  assert.throws(() => throwIfAborted(abort.signal), { name: 'AbortError' })
})
