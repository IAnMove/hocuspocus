import assert from 'node:assert/strict'
import test from 'node:test'
import {
  CATALOG_VERSION,
  CANDIDATE_SCENE_TEMPLATES,
} from '../src/features/sceneTemplates/catalog.ts'
import {
  candidateDemoBindings,
  candidateDemoScene,
} from '../src/features/sceneTemplates/demoScenes.ts'
import { compileCandidateScene } from '../src/features/sceneTemplates/compile.ts'
import { keyframes, layer, pulse } from '../src/features/sceneTemplates/sceneBuilders.ts'
import { parseSceneFile, serializeSceneFile } from '../src/lib/sceneFile.ts'
import { sceneFromLibraryPayload } from '../src/lib/sceneLibrary.ts'

const IDS = CANDIDATE_SCENE_TEMPLATES.map(template => template.id)
const VARIANTS = ['coral', 'teal']

const cases = () => IDS.flatMap(id => VARIANTS.map(variant => ({ id, variant })))

const build = ({ id, variant }) => candidateDemoScene(id, variant)

const bindingRecord = bindings => Object.fromEntries(
  Object.entries(bindings).map(([slot, value]) => [slot, {
    source: value.source,
    name: value.name,
    type: value.type,
  }]),
)

const provenanceRecord = scene => Object.fromEntries(
  (scene.narrative?.assets ?? []).map(asset => [asset.slot, {
    source: asset.source,
    name: asset.name,
    type: asset.type,
  }]),
)

const frameValues = frame => ({
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
  transform: layer.transform,
  animation: {
    start: layer.animation.start,
    end: layer.animation.end,
    keyframes: layer.animation.keyframes?.map(frameValues),
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

const assertSceneFrames = scene => {
  assert.ok(Number.isFinite(scene.duration) && scene.duration > 0)
  for (const layer of scene.layers) {
    assert.ok(Number.isFinite(layer.transform.x), `${layer.id} transform.x is finite`)
    assert.ok(Number.isFinite(layer.transform.y), `${layer.id} transform.y is finite`)
    assert.ok(Number.isFinite(layer.transform.scale), `${layer.id} transform.scale is finite`)
    assert.ok(layer.transform.scale > 0, `${layer.id} transform.scale is positive`)
    assert.ok(Number.isFinite(layer.animation.duration), `${layer.id} animation duration is finite`)
    assert.ok(layer.animation.duration > 0, `${layer.id} animation duration is positive`)

    for (const frame of [
      layer.animation.start,
      layer.animation.end,
      ...(layer.animation.keyframes ?? []),
    ]) {
      for (const key of ['x', 'y', 'scale', 'opacity', 'rotation']) {
        if (frame[key] !== undefined) assert.ok(Number.isFinite(frame[key]), `${layer.id}/${key} is finite`)
      }
      if (frame.scale !== undefined) assert.ok(frame.scale > 0, `${layer.id} frame scale is positive`)
      if (frame.time !== undefined) {
        assert.ok(Number.isFinite(frame.time), `${layer.id} frame time is finite`)
        assert.ok(frame.time >= 0, `${layer.id} frame time is not negative`)
        assert.ok(frame.time <= scene.duration, `${layer.id} frame time is inside the scene`)
      }
    }
  }
}

const assertRelationships = scene => {
  const ids = new Set(scene.layers.map(layer => layer.id))
  assert.equal(ids.size, scene.layers.length, 'layer IDs are unique')
  for (const layer of scene.layers) {
    const targets = [
      layer.relationship?.targetLayerId,
      layer.animation.orbit?.targetLayerId,
    ].filter(Boolean)
    for (const target of targets) {
      assert.notEqual(target, layer.id, `${layer.id} does not target itself`)
      assert.ok(ids.has(target), `${layer.id} target ${target} exists`)
    }
    if (layer.animation.orbit && layer.type === 'model3d') {
      assert.ok((layer.animation.orbit.count ?? 1) <= 1, `${layer.id} does not repeat a model3d orbit`)
    }
  }
}

test('all 24 candidate builders compile both deterministic demo variants', () => {
  assert.equal(IDS.length, 24)
  assert.equal(new Set(IDS).size, 24, 'candidate builder IDs are unique')
  const failures = []
  for (const current of cases()) {
    try {
      const first = build(current)
      const second = build(current)
      assert.deepEqual(first, second, `${current.id}/${current.variant} is deterministic`)
    } catch (error) {
      failures.push(`${current.id}/${current.variant}: ${error instanceof Error ? error.message : String(error)}`)
    }
  }
  assert.deepEqual(failures, [], 'every candidate ID has a working compiler for both variants')
})

test('all candidate scenes use provided_only and stay within the compositor budget', () => {
  for (const current of cases()) {
    const scene = build(current)
    assert.equal(scene.generationPolicy, 'provided_only', `${current.id}/${current.variant} policy`)
    assert.ok(scene.layers.length <= 24, `${current.id}/${current.variant} has at most 24 layers`)
    assert.ok(scene.layers.filter(layer => layer.type === 'model3d').length <= 2, `${current.id}/${current.variant} has at most 2 GLB layers`)
    for (const layer of scene.layers) {
      if (layer.type === 'model3d' && layer.animation.orbit) {
        assert.ok((layer.animation.orbit.count ?? 1) <= 1, `${current.id}/${current.variant}/${layer.id} has no repeated model orbit`)
      }
    }
  }
})

test('all candidate scenes preserve exact slot sources in candidate provenance', () => {
  for (const current of cases()) {
    const scene = build(current)
    assert.equal(scene.narrative?.templateId, current.id)
    assert.deepEqual(
      provenanceRecord(scene),
      bindingRecord(candidateDemoBindings(current.id, current.variant)),
      `${current.id}/${current.variant} slot provenance`,
    )
    assert.equal(scene.narrative?.controls.catalogVersion, CATALOG_VERSION)
    assert.equal(scene.narrative?.controls.templateVersion, 1)
    assert.equal(scene.narrative?.controls.reviewStatus, 'candidate')
  }
})

test('all candidate scenes have finite positive frames and valid relationship targets', () => {
  for (const current of cases()) {
    const scene = build(current)
    assertSceneFrames(scene)
    assertRelationships(scene)
  }
})

test('keyframed templates expose the actual endpoint poses to legacy editor controls', () => {
  for (const current of cases()) {
    for (const item of build(current).layers) {
      const frames = item.animation.keyframes
      if (!frames?.length) continue
      for (const key of ['x', 'y', 'scale', 'rotation', 'opacity']) {
        assert.equal(item.animation.start[key], frames[0][key], `${current.id}/${item.id}/start/${key}`)
        assert.equal(item.animation.end[key], frames.at(-1)[key], `${current.id}/${item.id}/end/${key}`)
      }
      assert.equal(item.animation.start.id, undefined)
      assert.equal(item.animation.end.time, undefined)
    }
  }
  const item = layer('test', 'model3d', '/api/v1/file/ship.glb', 4)
  item.transform.rotationX = 65
  assert.deepEqual(keyframes(item, []).animation.start, item.animation.start)
  const animated = keyframes(item, [{ at: 0, x: 10 }, { at: 1, x: 80 }])
  assert.equal(animated.animation.start.rotationX, 65)
  assert.equal(animated.animation.end.rotationX, 65)
})

test('compiler rejects repeated GLB sources and mismatched inline MIME types', () => {
  const pair = candidateDemoBindings('space-chase', 'coral')
  assert.throws(() => compileCandidateScene('space-chase', { ...pair, prop: pair.hero }), /GLB.*repeated/i)
  assert.throws(() => compileCandidateScene('space-chase', {
    ...pair, hero: { ...pair.hero, source: 'data:image/png;base64,AA==' },
  }), /MIME/i)
  const cinema = candidateDemoBindings('cinema-establishing', 'coral')
  assert.throws(() => compileCandidateScene('cinema-establishing', {
    ...cinema, plate: { ...cinema.plate, source: pair.hero.source },
  }), /MIME/i)
  assert.doesNotThrow(() => compileCandidateScene('cinema-establishing', {
    ...cinema, plate: { type: 'image', source: '/api/v1/files/asset-id' },
  }))
})

test('chorus camera pulses around its declared pose without discarding animation', () => {
  const camera = candidateDemoScene('music-chorus').layers.find(item => item.type === 'camera')
  assert.equal(camera.animation.keyframes[0].scale, 1.04)
  assert.equal(camera.animation.keyframes.at(-1).scale, 1.04)
  assert.equal(Math.max(...camera.animation.keyframes.map(frame => frame.scale)), 1.04 * (1 + .09 * .6))
  assert.throws(() => pulse({ duration: 4, bpm: 120, intensity: .6, bindings: {} }, camera), /existing keyframes/i)
})

test('all 24 builders have distinct motion fingerprints beyond asset sources and names', () => {
  const fingerprints = new Map()
  for (const id of IDS) {
    const fingerprint = motionFingerprint(build({ id, variant: 'coral' }))
    const previous = fingerprints.get(fingerprint)
    assert.equal(previous, undefined, `${id} shares its motion fingerprint with ${previous ?? 'another candidate'}`)
    fingerprints.set(fingerprint, id)
  }
  assert.equal(fingerprints.size, 24)
})

test('candidate scenes round-trip through scene JSON and MP4 sidecar payload shape', () => {
  for (const current of cases()) {
    const original = build(current)
    const parsed = parseSceneFile(serializeSceneFile(original))
    const recovered = sceneFromLibraryPayload({ params: { scene: parsed } })
    assert.equal(recovered.narrative?.templateId, current.id)
    assert.equal(recovered.narrative?.controls.catalogVersion, CATALOG_VERSION)
    assert.equal(recovered.narrative?.controls.templateVersion, 1)
    assert.equal(recovered.narrative?.controls.reviewStatus, 'candidate')
    assert.deepEqual(provenanceRecord(recovered), provenanceRecord(original), `${current.id}/${current.variant} recovered provenance`)
  }
})

test('candidate compiler rejects unknown, incomplete, invalid, unsafe, and out-of-range inputs', () => {
  const valid = candidateDemoBindings('cinema-establishing', 'coral')

  assert.throws(
    () => compileCandidateScene('unknown-candidate', {}),
    /Unknown candidate scene template: unknown-candidate/,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', {}),
    /Required slot hero/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', { ...valid, unknown: valid.hero }),
    /unknown slot/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', { ...valid, hero: { ...valid.hero, type: 'video' } }),
    /slot hero no admite video/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', valid, { duration: Number.NaN }),
    /Duration/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', valid, { duration: 13 }),
    /Duration/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', { ...valid, hero: { ...valid.hero, source: 'blob:unsafe-preview' } }),
    /asset|referencia|durable/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', { ...valid, hero: { ...valid.hero, source: 'javascript:alert(1)' } }),
    /asset|referencia|durable/i,
  )
})
