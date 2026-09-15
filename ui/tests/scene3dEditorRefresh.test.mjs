import assert from 'node:assert/strict'
import test from 'node:test'
import { Object3D } from 'three'
import { SCENE3D_TEMPLATES, applyScene3DTemplate, remountScene3DTemplate, TEMPLATE_CATEGORIES } from '../src/features/scene3d/templates.ts'
import { SCENE3D_TEMPLATE_IDS } from '../src/features/scene3d/types.ts'
import { cameraEyeAtTime, cameraLookAtTime, projectPoint } from '../src/features/scene3d/camera.ts'
import { parseScene3DDocument } from '../src/features/scene3d/document.ts'
import { scene3dOutputDuration, scene3dPlaybackSpeed } from '../src/features/scene3d/clock.ts'
import { world3dExportPlan } from '../src/features/scene3d/exportMp4.ts'
import { world3dRecordingStub } from '../src/features/scene3d/publish.ts'
import { retainSlotClipCatalogs } from '../src/features/scene3d/clips.ts'
import { transformPatch } from '../src/features/scene3d/transformGizmo.ts'
import { ALL_SCENE_TEMPLATES } from '../src/features/sceneTemplates/catalog.ts'
import { candidateDemoScene } from '../src/features/sceneTemplates/demoScenes.ts'
import { serializeSceneFile, parseSceneFile } from '../src/lib/sceneFile.ts'

test('all 3D shots roundtrip and produce finite, nondegenerate cameras', () => {
  assert.equal(SCENE3D_TEMPLATES.length, SCENE3D_TEMPLATE_IDS.length)
  assert.equal(new Set(SCENE3D_TEMPLATE_IDS).size, SCENE3D_TEMPLATE_IDS.length)
  for (const template of SCENE3D_TEMPLATES) {
    const scene = applyScene3DTemplate(template.id)
    assert.ok(TEMPLATE_CATEGORIES[template.id])
    assert.equal(parseScene3DDocument(JSON.parse(JSON.stringify(scene)))?.templateId, template.id)
    assert.equal(new Set(scene.slots.map(slot => slot.id)).size, scene.slots.length)
    for (const phase of [0, 0.25, 0.5, 0.75, 1]) {
      const eye = cameraEyeAtTime(scene.camera, phase * scene.duration, scene.duration, scene.slots)
      const look = cameraLookAtTime(scene.camera, phase * scene.duration, scene.duration, scene.slots)
      assert.ok([...eye, ...look].every(Number.isFinite), template.id)
      assert.ok(Math.hypot(...eye.map((value, i) => value - look[i])) > 0.2, template.id)
      assert.ok(projectPoint(look, eye, look, scene.camera.fov, 16 / 9), template.id)
    }
  }
})

test('new layouts are distinct and existing shots get different camera compositions', () => {
  const fingerprints = SCENE3D_TEMPLATES.map(template => {
    const scene = applyScene3DTemplate(template.id)
    return JSON.stringify([scene.camera, scene.slots, scene.dressing])
  })
  assert.equal(new Set(fingerprints).size, SCENE3D_TEMPLATE_IDS.length)
})

test('shot changes preserve asset identity and clip choices without mutating the previous scene', () => {
  const original = applyScene3DTemplate('two-shot')
  Object.assign(original.slots[0], { sourceUrl: '/api/v1/file/hero.glb?workspace=test', sourceRef: { workspaceId: 'test', filename: 'hero.glb', url: '/api/v1/file/hero.glb?workspace=test', assetId: 'canonical-hero' }, clip: { index: 2, name: 'Walk exact' } })
  original.playbackSpeed = 2
  const before = JSON.stringify(original)
  const next = remountScene3DTemplate('duo-diagonal', original)
  assert.deepEqual(next.slots[0].sourceRef, original.slots[0].sourceRef)
  assert.deepEqual(next.slots[0].clip, original.slots[0].clip)
  assert.notDeepEqual(next.slots[0].position, original.slots[0].position)
  assert.equal(next.playbackSpeed, 2)
  assert.equal(JSON.stringify(original), before)
  assert.equal(remountScene3DTemplate('duo-diagonal', original, false).slots[0].sourceUrl, '')
})

test('rate changes output duration and preserves complete timeline coverage and metadata', () => {
  for (const speed of [0.25, 0.5, 1, 2, 4]) {
    const scene = { ...applyScene3DTemplate('two-shot'), playbackSpeed: speed }
    const duration = scene3dOutputDuration(scene)
    const plan = world3dExportPlan(duration, scene.fps)
    assert.equal(duration, 6 / speed)
    assert.equal(plan.count, Math.round(duration * scene.fps))
    assert.equal(world3dRecordingStub(scene).duration, duration)
    assert.ok(Math.abs(plan.times.at(-1) * speed - scene.duration) <= speed / scene.fps + 1e-8)
    assert.equal(parseScene3DDocument(JSON.parse(JSON.stringify(scene))).playbackSpeed, speed)
  }
  assert.equal(world3dExportPlan(6, 24).count, 144)
  assert.equal(world3dExportPlan(6, 24).fps, 24)
  assert.equal(world3dExportPlan(6, 30).fps, 30)
  assert.equal(world3dExportPlan(6, 60).fps, 60)
  assert.equal(scene3dPlaybackSpeed(undefined), 1)
  assert.equal(scene3dPlaybackSpeed(NaN), 1)
  assert.equal(scene3dPlaybackSpeed(-1), 0.25)
  assert.equal(scene3dPlaybackSpeed(90), 4)
})

test('gizmo converts translation, yaw and uniform scale into document transforms', () => {
  const proxy = new Object3D()
  proxy.position.set(-1.5, 2, 3.75)
  proxy.rotation.y = Math.PI / 2
  proxy.scale.set(1.5, 2, 3)
  assert.deepEqual(transformPatch(proxy, 'translate', 'Z'), { position: [-1.5, 2, 3.75] })
  assert.deepEqual(transformPatch(proxy, 'rotate', 'Y'), { rotationY: Math.PI / 2 })
  assert.deepEqual(transformPatch(proxy, 'scale', 'X'), { scale: 1.5 })
  assert.deepEqual(transformPatch(proxy, 'scale', 'Y'), { scale: 2 })
  assert.deepEqual(transformPatch(proxy, 'scale', 'Z'), { scale: 3 })
  proxy.scale.setScalar(-2)
  assert.deepEqual(transformPatch(proxy, 'scale', 'XYZ'), { scale: 0.05 })
})

test('all 48 layer templates get an editable depth finish without rewriting prompts or assets', () => {
  for (const template of ALL_SCENE_TEMPLATES) {
    const scene = candidateDemoScene(template.id)
    assert.equal(scene.narrative.controls.finishVersion, 1)
    assert.equal(scene.narrative.prompt, template.promptExample)
    assert.equal(scene.generationPolicy, 'provided_only')
    assert.ok(scene.layers.some(layer => layer.effects), template.id)
    assert.ok(scene.layers.length <= 24)
    const restored = parseSceneFile(serializeSceneFile(scene))
    assert.deepEqual(restored.narrative, scene.narrative)
  }
})


test('reusing a GLB keeps its animation dropdown; replacing it drops stale clips', () => {
  const previous = [{ id: 'subject_1', sourceUrl: '/a.glb' }, { id: 'subject_2', sourceUrl: '/b.glb' }]
  const clips = [{ index: 1, name: 'Running', durationSeconds: 2 }]
  const catalogs = { subject_1: clips, subject_2: clips }
  const next = [{ id: 'subject_1', sourceUrl: '/a.glb' }, { id: 'subject_2', sourceUrl: '/c.glb' }]
  assert.deepEqual(retainSlotClipCatalogs(previous, next, catalogs), { subject_1: clips })
  assert.deepEqual(retainSlotClipCatalogs(previous, [], catalogs), {})
})
