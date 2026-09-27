import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ALL_SCENE_TEMPLATES,
  CANDIDATE_SCENE_TEMPLATES,
  EXPANDED_CATALOG_VERSION,
  getCandidateSceneTemplate,
} from '../src/features/sceneTemplates/catalog.ts'
import { MUSIC_MOTION_TEMPLATES } from '../src/features/sceneTemplates/musicMotionCatalog.ts'
import { compileCandidateScene } from '../src/features/sceneTemplates/compile.ts'
import { parseSceneFile, serializeSceneFile } from '../src/lib/sceneFile.ts'
import { sceneFromLibraryPayload } from '../src/lib/sceneLibrary.ts'

const MUSIC_SLOT_IDS = new Set(['subject_1', 'subject_2', 'background', 'prop_1'])

const bindingFor = (template, slot, index) => {
  const filename = `${template.id}-${slot.id}-${index}.png`
  return {
    type: 'image',
    source: `/api/v1/file/${encodeURIComponent(filename)}?workspace=music-motion-tests`,
    name: `${template.id} · identidad ${slot.id} ${index}`,
    catalogAtAssignment: {
      assetId: `asset-${template.id}-${slot.id}-${index}`,
      workspaceId: 'music-motion-tests',
      filename,
      metadataStatus: 'canonical',
      originTool: 'music-motion-test',
    },
  }
}

const bindingsFor = template => Object.fromEntries(
  template.slots.map((slot, index) => [slot.id, bindingFor(template, slot, index)]),
)

const templateWithSuffix = suffix => {
  const template = MUSIC_MOTION_TEMPLATES.find(item => item.id === `music-${suffix}` || item.id.endsWith(`-${suffix}`))
  assert.ok(template, `missing music motion template for ${suffix}`)
  return template
}

const frameProjection = frame => ({
  time: frame.time,
  x: frame.x,
  y: frame.y,
  scale: frame.scale,
  opacity: frame.opacity,
  rotation: frame.rotation,
  curve: frame.curve,
})

const motionFingerprint = scene => JSON.stringify(scene.layers.map(layer => ({
  type: layer.type,
  visible: layer.visible,
  z: layer.z,
  fill: layer.fill,
  parallax: layer.parallax,
  atmosphere: layer.atmosphere,
  relationship: layer.relationship,
  effects: layer.effects,
  strip: layer.strip,
  transform: layer.transform,
  animation: {
    start: layer.animation.start,
    end: layer.animation.end,
    keyframes: layer.animation.keyframes?.map(frameProjection),
    duration: layer.animation.duration,
    curve: layer.animation.curve,
    offset: layer.animation.offset,
    speed: layer.animation.speed,
    loop: layer.animation.loop,
    trimStart: layer.animation.trimStart,
    trimEnd: layer.animation.trimEnd,
    shake: layer.animation.shake,
    spin: layer.animation.spin,
    rotationSpeed: layer.animation.rotationSpeed,
    orbit: layer.animation.orbit,
  },
})))

const assertFinitePose = (pose, label) => {
  for (const key of ['x', 'y', 'scale', 'opacity', 'rotation']) {
    if (pose[key] !== undefined) assert.ok(Number.isFinite(pose[key]), `${label}/${key} must be finite`)
  }
  if (pose.scale !== undefined) assert.ok(pose.scale > 0, `${label}/scale must be positive`)
}

const assertSceneShape = scene => {
  assert.ok(Number.isFinite(scene.duration) && scene.duration > 0, 'scene duration must be finite and positive')
  assert.ok(scene.layers.length <= 24, 'scene must stay within the 24-layer budget')
  assert.ok(scene.layers.filter(layer => layer.type === 'model3d').length <= 2, 'scene must stay within the 2-GLB budget')

  const ids = new Set(scene.layers.map(layer => layer.id))
  assert.equal(ids.size, scene.layers.length, 'scene layer IDs must be unique')
  for (const layer of scene.layers) {
    assertFinitePose(layer.transform, `${layer.id}/transform`)
    assert.ok(Number.isFinite(layer.animation.duration) && layer.animation.duration > 0, `${layer.id}/duration must be positive`)
    assertFinitePose(layer.animation.start, `${layer.id}/start`)
    assertFinitePose(layer.animation.end, `${layer.id}/end`)

    let previousTime = -Infinity
    for (const frame of layer.animation.keyframes ?? []) {
      assert.ok(Number.isFinite(frame.time), `${layer.id}/frame time must be finite`)
      assert.ok(frame.time >= 0 && frame.time <= scene.duration, `${layer.id}/frame time must be inside the scene`)
      assert.ok(frame.time >= previousTime, `${layer.id}/keyframes must be ordered`)
      previousTime = frame.time
      assertFinitePose(frame, `${layer.id}/frame-${frame.id}`)
    }

    const targetIds = [
      layer.relationship?.targetLayerId,
      layer.animation.orbit?.targetLayerId,
    ].filter(Boolean)
    for (const targetId of targetIds) {
      assert.notEqual(targetId, layer.id, `${layer.id} must not target itself`)
      assert.ok(ids.has(targetId), `${layer.id} target ${targetId} must exist`)
    }
  }
}

const assetBySlot = scene => new Map((scene.narrative?.assets ?? []).map(asset => [asset.slot, asset]))

test('expanded catalog keeps the 24 legacy candidates intact and adds 24 music candidates', () => {
  assert.equal(CANDIDATE_SCENE_TEMPLATES.length, 24)
  assert.equal(MUSIC_MOTION_TEMPLATES.length, 24)
  assert.equal(ALL_SCENE_TEMPLATES.length, 48)
  assert.deepEqual(
    ALL_SCENE_TEMPLATES.slice(0, CANDIDATE_SCENE_TEMPLATES.length),
    CANDIDATE_SCENE_TEMPLATES,
    'the expanded list must not rewrite the legacy prefix',
  )

  const legacyIds = CANDIDATE_SCENE_TEMPLATES.map(template => template.id)
  const musicIds = MUSIC_MOTION_TEMPLATES.map(template => template.id)
  assert.equal(new Set(legacyIds).size, 24)
  assert.equal(new Set(musicIds).size, 24)
  assert.equal(new Set([...legacyIds, ...musicIds]).size, 48)

  for (const template of MUSIC_MOTION_TEMPLATES) {
    assert.equal(template.status, 'candidate')
    assert.equal(template.version, 1)
    assert.equal(template.family, 'music')
    assert.ok(template.description.length > 0)
    assert.ok(template.promptExample.includes(template.id))
    assert.ok(template.defaultDuration >= 3 && template.defaultDuration <= 12)
    for (const slot of template.slots) {
      assert.ok(MUSIC_SLOT_IDS.has(slot.id), `${template.id} uses only expanded slot names`)
      assert.deepEqual(slot.kinds, ['image'], `${template.id}/${slot.id} is image-only`)
      assert.ok(slot.description.length > 0, `${template.id}/${slot.id} explains its role`)
    }
    assert.ok(template.slots.some(slot => slot.id === 'subject_1' && slot.required))
    assert.ok(template.slots.some(slot => slot.id === 'background' && slot.required))
    assert.equal(getCandidateSceneTemplate(template.id), template)
  }
})

test('every music motion compiles deterministically with provided assets and exact provenance', () => {
  for (const template of MUSIC_MOTION_TEMPLATES) {
    const bindings = bindingsFor(template)
    const first = compileCandidateScene(template.id, bindings)
    const second = compileCandidateScene(template.id, bindings)

    assert.deepEqual(first, second, `${template.id} must compile deterministically`)
    assert.equal(first.generationPolicy, 'provided_only')
    assert.equal(first.narrative?.templateId, template.id)
    assert.equal(first.narrative?.controls.catalogVersion, EXPANDED_CATALOG_VERSION)
    assert.equal(first.narrative?.controls.templateVersion, 1)
    assert.equal(first.narrative?.controls.reviewStatus, 'candidate')
    assertSceneShape(first)

    const assets = assetBySlot(first)
    assert.equal(assets.size, Object.keys(bindings).length)
    for (const [slotId, binding] of Object.entries(bindings)) {
      const recorded = assets.get(slotId)
      assert.ok(recorded, `${template.id}/${slotId} must remain in narrative.assets`)
      assert.equal(recorded.source, binding.source)
      assert.equal(recorded.name, binding.name)
      assert.equal(recorded.type, binding.type)
      assert.deepEqual(recorded.catalogAtAssignment, binding.catalogAtAssignment)
    }

    const recovered = sceneFromLibraryPayload({ params: { scene: parseSceneFile(serializeSceneFile(first)) } })
    assert.equal(recovered.narrative?.templateId, template.id)
    assert.equal(recovered.generationPolicy, 'provided_only')
    assert.deepEqual(recovered.narrative?.assets, first.narrative?.assets)
    assert.equal(
      serializeSceneFile(recovered),
      serializeSceneFile(first),
      `${template.id} must remain serializable after scene-file round-trip`,
    )
  }
})

test('music motion compiler rejects missing, unknown, wrong-type, unsafe, and invalid inputs', () => {
  const twoSubjectTemplate = MUSIC_MOTION_TEMPLATES.find(template => template.slots.some(slot => slot.id === 'subject_2'))
  assert.ok(twoSubjectTemplate, 'the pack must contain a two-subject template')
  const valid = bindingsFor(twoSubjectTemplate)

  const missingRequired = { ...valid }
  delete missingRequired.subject_2
  assert.throws(() => compileCandidateScene(twoSubjectTemplate.id, missingRequired), /Required slot subject_2/i)

  assert.throws(
    () => compileCandidateScene(twoSubjectTemplate.id, { ...valid, unknown_slot: valid.subject_1 }),
    /unknown slot/i,
  )

  const propTemplate = MUSIC_MOTION_TEMPLATES.find(template => template.slots.some(slot => slot.id === 'prop_1'))
  assert.ok(propTemplate, 'the pack must contain a prop_1 template')
  const propBindings = bindingsFor(propTemplate)
  assert.throws(
    () => compileCandidateScene(propTemplate.id, { ...propBindings, prop_1: { ...propBindings.prop_1, type: 'model3d', source: '/api/v1/file/prop.glb' } }),
    /slot prop_1 no admite model3d/i,
  )

  assert.throws(() => compileCandidateScene('music-motion-unknown', {}), /Unknown candidate scene template/i)
  assert.throws(() => compileCandidateScene(twoSubjectTemplate.id, valid, { duration: Number.NaN }), /Duration/i)
  assert.throws(() => compileCandidateScene(twoSubjectTemplate.id, valid, { duration: 13 }), /Duration/i)
  assert.throws(() => compileCandidateScene(twoSubjectTemplate.id, {
    ...valid,
    subject_1: { ...valid.subject_1, source: 'blob:https://example.invalid/unsafe' },
  }), /asset|blob|durable/i)
})

test('two-subject choreography preserves distinct identities without swapping slots', () => {
  const template = MUSIC_MOTION_TEMPLATES.find(item => item.slots.some(slot => slot.id === 'subject_2'))
  assert.ok(template)
  const bindings = bindingsFor(template)
  assert.notEqual(bindings.subject_1.source, bindings.subject_2.source)
  assert.notEqual(bindings.subject_1.name, bindings.subject_2.name)

  const scene = compileCandidateScene(template.id, bindings)
  const subject1 = scene.layers.find(layer => layer.id === 'subject_1')
  const subject2 = scene.layers.find(layer => layer.id === 'subject_2')
  assert.equal(subject1?.source, bindings.subject_1.source)
  assert.equal(subject2?.source, bindings.subject_2.source)
  assert.equal(assetBySlot(scene).get('subject_1')?.source, bindings.subject_1.source)
  assert.equal(assetBySlot(scene).get('subject_2')?.source, bindings.subject_2.source)
})

test('musical identity slots reject repeated sources and canonical asset aliases', () => {
  const template = MUSIC_MOTION_TEMPLATES.find(item => item.slots.some(slot => slot.id === 'subject_2'))
  assert.ok(template)
  const bindings = bindingsFor(template)

  assert.throws(
    () => compileCandidateScene(template.id, {
      ...bindings,
      subject_2: { ...bindings.subject_2, source: bindings.subject_1.source },
    }),
    /subject_1.*subject_2.*source matches/i,
  )

  assert.throws(
    () => compileCandidateScene(template.id, {
      ...bindings,
      subject_2: {
        ...bindings.subject_2,
        source: '/api/v1/file/another-subject.png?workspace=music-motion-tests',
        catalogAtAssignment: { ...bindings.subject_2.catalogAtAssignment, assetId: bindings.subject_1.catalogAtAssignment.assetId },
      },
    }),
    /subject_1.*subject_2.*canonical assetId/i,
  )

  assert.doesNotThrow(() => compileCandidateScene(template.id, {
    ...bindings,
    subject_2: {
      ...bindings.subject_2,
      source: '/api/v1/file/legitimate-variant.png?workspace=music-motion-tests',
      catalogAtAssignment: { ...bindings.subject_2.catalogAtAssignment, assetId: 'asset-legitimate-variant' },
    },
  }))
})

test('legacy hero and prop are outside the musical identity duplicate rule', () => {
  const legacy = CANDIDATE_SCENE_TEMPLATES.find(template => template.id === 'music-duet')
  assert.ok(legacy)
  const bindings = bindingsFor(legacy)
  assert.doesNotThrow(() => compileCandidateScene(legacy.id, {
    ...bindings,
    prop: { ...bindings.prop, source: bindings.hero.source },
  }))
})

test('all 24 music motion builders have distinct choreographies beyond assets and names', () => {
  const fingerprints = new Map()
  for (const template of MUSIC_MOTION_TEMPLATES) {
    const fingerprint = motionFingerprint(compileCandidateScene(template.id, bindingsFor(template)))
    const previous = fingerprints.get(fingerprint)
    assert.equal(previous, undefined, `${template.id} shares a choreography with ${previous ?? 'another template'}`)
    fingerprints.set(fingerprint, template.id)
  }
  assert.equal(fingerprints.size, MUSIC_MOTION_TEMPLATES.length)
})

test('spiral-exit rotates and shrinks subject_1', () => {
  const template = templateWithSuffix('spiral-exit')
  const scene = compileCandidateScene(template.id, bindingsFor(template))
  const subject = scene.layers.find(layer => layer.id === 'subject_1')
  assert.ok(subject?.animation.keyframes?.length)
  const frames = subject.animation.keyframes
  assert.notEqual(frames[0].rotation, frames.at(-1).rotation)
  assert.ok(frames.at(-1).scale < frames[0].scale, 'spiral-exit must shrink the subject as it leaves')
})

test('speed-flight crosses left-to-right while its background strip moves oppositely', () => {
  const template = templateWithSuffix('speed-flight')
  const scene = compileCandidateScene(template.id, bindingsFor(template))
  const subject = scene.layers.find(layer => layer.id === 'subject_1')
  const background = scene.layers.find(layer => layer.strip?.enabled)
  assert.ok(subject?.animation.keyframes?.length)
  assert.ok(background?.strip?.enabled)
  assert.ok(subject.animation.keyframes.at(-1).x > subject.animation.keyframes[0].x)
  assert.equal(background.strip.direction, 'left')
  assert.ok(background.strip.speed > 0)
})
