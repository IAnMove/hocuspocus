import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ALL_SCENE_TEMPLATES,
  SCENE_TEMPLATE_ALIASES,
  getCandidateSceneTemplate,
  templateCatalogVersion,
} from '../src/features/sceneTemplates/catalog.ts'
import {
  candidateDemoBindings,
  candidateDemoScene,
} from '../src/features/sceneTemplates/demoScenes.ts'
import { compileCandidateScene } from '../src/features/sceneTemplates/compile.ts'
import { keyframes, layer, pulse } from '../src/features/sceneTemplates/sceneBuilders.ts'
import { parseSceneFile, serializeSceneFile } from '../src/lib/sceneFile.ts'
import { sceneFromLibraryPayload } from '../src/lib/sceneLibrary.ts'

const IDS = ALL_SCENE_TEMPLATES.map(template => template.id)
const versionOf = id => templateCatalogVersion(getCandidateSceneTemplate(id))
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

test('all 41 cards compile both deterministic demo variants', () => {
  assert.equal(IDS.length, 41)
  assert.equal(new Set(IDS).size, 41, 'card IDs are unique')
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
    assert.equal(scene.narrative?.controls.catalogVersion, versionOf(current.id))
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
  assert.throws(() => compileCandidateScene('space-chase', { ...pair, prop_1: pair.subject_1 }), /GLB.*repetid/i)
  assert.throws(() => compileCandidateScene('space-chase', {
    ...pair, subject_1: { ...pair.subject_1, source: 'data:image/png;base64,AA==' },
  }), /MIME/i)
  const cinema = candidateDemoBindings('cinema-establishing', 'coral')
  assert.throws(() => compileCandidateScene('cinema-establishing', {
    ...cinema, background: { ...cinema.background, source: pair.subject_1.source },
  }), /MIME/i)
  assert.doesNotThrow(() => compileCandidateScene('cinema-establishing', {
    ...cinema, background: { type: 'image', source: '/api/v1/files/asset-id' },
  }))
})

test('the chorus alias pulses the camera around its declared pose without discarding animation', () => {
  const camera = compileCandidateScene('music-chorus', candidateDemoBindings('music-pulse'), { drift: 0 }).layers.find(item => item.type === 'camera')
  assert.equal(camera.animation.keyframes[0].scale, 1.04)
  assert.equal(camera.animation.keyframes.at(-1).scale, 1.04)
  assert.equal(Math.max(...camera.animation.keyframes.map(frame => frame.scale)), 1.04 * (1 + .09 * .6))
  assert.throws(() => pulse({ duration: 4, bpm: 120, intensity: .6, bindings: {} }, camera), /keyframes existentes/i)
})

test('all 41 cards have distinct motion fingerprints beyond asset sources and names', () => {
  const fingerprints = new Map()
  for (const id of IDS) {
    const fingerprint = motionFingerprint(build({ id, variant: 'coral' }))
    const previous = fingerprints.get(fingerprint)
    assert.equal(previous, undefined, `${id} shares its motion fingerprint with ${previous ?? 'another candidate'}`)
    fingerprints.set(fingerprint, id)
  }
  assert.equal(fingerprints.size, 41)
})

test('candidate scenes round-trip through scene JSON and MP4 sidecar payload shape', () => {
  for (const current of cases()) {
    const original = build(current)
    const parsed = parseSceneFile(serializeSceneFile(original))
    const recovered = sceneFromLibraryPayload({ params: { scene: parsed } })
    assert.equal(recovered.narrative?.templateId, current.id)
    assert.equal(recovered.narrative?.controls.catalogVersion, versionOf(current.id))
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
    /slot obligatorio subject_1/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', { ...valid, unknown: valid.subject_1 }),
    /slot desconocido/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', { ...valid, subject_1: { ...valid.subject_1, type: 'video' } }),
    /slot subject_1 no admite video/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', valid, { duration: Number.NaN }),
    /Duración/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', valid, { duration: 13 }),
    /Duración/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', { ...valid, subject_1: { ...valid.subject_1, source: 'blob:unsafe-preview' } }),
    /asset|referencia|durable/i,
  )
  assert.throws(
    () => compileCandidateScene('cinema-establishing', { ...valid, subject_1: { ...valid.subject_1, source: 'javascript:alert(1)' } }),
    /asset|referencia|durable/i,
  )
})

const choiceValues = template => Object.entries(template.controls)
  .filter(([, spec]) => spec.kind === 'choice')
  .flatMap(([key, spec]) => spec.options.map(value => ({ [key]: value })))

const bindingsFor = (id, controls = {}) => {
  const bindings = candidateDemoBindings(id)
  // Optional slots a choice needs (pinball's bouncing prop) get the demo prop.
  if (controls.bouncer === 'prop') bindings.prop_1 = demoProp()
  return bindings
}
const demoProp = () => candidateDemoBindings('music-crowd-surf').prop_1

test('every card compiles at its defaults, at 3 and 12 seconds, and at every choice it offers', () => {
  const failures = []
  for (const template of ALL_SCENE_TEMPLATES) {
    for (const controls of [{}, { duration: 3 }, { duration: 12 }, ...choiceValues(template)]) {
      try {
        const scene = compileCandidateScene(template.id, bindingsFor(template.id, controls), controls)
        assertSceneFrames(scene)
        assertRelationships(scene)
        for (const [key, value] of Object.entries(controls)) assert.equal(scene.narrative.controls[key], value)
      } catch (error) {
        failures.push(`${template.id} ${JSON.stringify(controls)}: ${error instanceof Error ? error.message : String(error)}`)
      }
    }
  }
  assert.deepEqual(failures, [])
})

test('every alias compiles as its card with its preset, records the alias, and lets a caller override', () => {
  for (const [alias, { card, preset }] of Object.entries(SCENE_TEMPLATE_ALIASES)) {
    const scene = compileCandidateScene(alias, bindingsFor(card, preset))
    assert.equal(scene.narrative.templateId, card)
    assert.equal(scene.narrative.controls.alias, alias)
    for (const [key, value] of Object.entries(preset)) assert.equal(scene.narrative.controls[key], value)
    const direct = compileCandidateScene(card, bindingsFor(card, preset), preset)
    assert.deepEqual(scene.layers, direct.layers, `${alias} is ${card} with ${JSON.stringify(preset)}`)
  }
  const overridden = compileCandidateScene('music-stage', candidateDemoBindings('music-pulse'), { camera: 'push' })
  assert.equal(overridden.narrative.controls.camera, 'push')
})

test('merged cards keep the look of the card they absorbed', () => {
  const layerIds = scene => scene.layers.map(item => item.id)
  const explosion = compileCandidateScene('space-explosion', candidateDemoBindings('space-broadside'))
  assert.deepEqual(layerIds(explosion), ['background', 'subject_1', 'prop_1', 'beam-0', 'explosion-flash', 'explosion-debris', 'camera'])
  assert.equal(explosion.layers.find(item => item.id === 'camera').animation.shake.amount, .18)
  assert.ok(layerIds(compileCandidateScene('space-shield', candidateDemoBindings('space-broadside'))).includes('impact-shield'))
  assert.ok(layerIds(compileCandidateScene('cinema-isolation', candidateDemoBindings('cinema-establishing'))).includes('atmosphere-rain'))
  assert.ok(layerIds(compileCandidateScene('music-parallax', candidateDemoBindings('cinema-tracking'))).includes('atmosphere-speedlines'))
  const swarm = compileCandidateScene('music-satellite-swarm', candidateDemoBindings('music-orbit'))
  assert.equal(swarm.layers.find(item => item.id === 'subject_1').animation.keyframes, undefined, 'the figure holds')
  assert.equal(swarm.layers.find(item => item.id === 'prop_1').animation.orbit.count, 5)
  const ricochet = compileCandidateScene('music-ricochet-pass', { ...candidateDemoBindings('music-pinball'), prop_1: demoProp() })
  assert.equal(ricochet.layers.find(item => item.id === 'prop_1').transform.scale, .18)
  assert.throws(() => compileCandidateScene('music-ricochet-pass', candidateDemoBindings('music-pinball')), /slot obligatorio prop_1/)
})

test('choice and text controls are checked with stable codes', () => {
  const bindings = candidateDemoBindings('music-pulse')
  const codeOf = fn => { try { fn() } catch (error) { return error.code } return 'compiled' }
  assert.equal(codeOf(() => compileCandidateScene('music-pulse', bindings, { camera: 'dolly' })), 'template_bad_control')
  assert.equal(codeOf(() => compileCandidateScene('music-pulse', bindings, { camera: 3 })), 'template_bad_control')
  assert.equal(codeOf(() => compileCandidateScene('music-pulse', bindings, { mood: 'calm' })), 'template_bad_control')
  assert.equal(codeOf(() => compileCandidateScene('music-pulse', bindings, { drift: 1.5 })), 'template_bad_control')
  const history = candidateDemoBindings('documentary-history')
  assert.equal(codeOf(() => compileCandidateScene('documentary-history', history, { caption: 'x'.repeat(81) })), 'template_bad_control')
  assert.equal(codeOf(() => compileCandidateScene('documentary-history', history, { caption: '🎞'.repeat(80) })), 'compiled', 'code points, not UTF-16 units')
  assert.equal(codeOf(() => compileCandidateScene('trailer-teaser', history)), 'template_retired')
  assert.equal(codeOf(() => compileCandidateScene('cinema-two-shot', { ...candidateDemoBindings('cinema-two-shot'), prop: candidateDemoBindings('cinema-two-shot').subject_2 })), 'slot_alias_conflict')
})

test('old slot names compile to the new layer ids', () => {
  const art = candidateDemoBindings('cinema-two-shot')
  const scene = compileCandidateScene('cinema-two-shot', { hero: art.subject_1, plate: art.background, prop: art.subject_2 })
  assert.deepEqual(scene.layers.map(item => item.id), ['background', 'subject_1', 'subject_2', 'camera'])
  assert.deepEqual(scene.narrative.assets.map(item => item.slot), ['subject_1', 'background', 'subject_2'])
})
