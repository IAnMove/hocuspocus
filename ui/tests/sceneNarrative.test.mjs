import assert from 'node:assert/strict'
import test from 'node:test'
import { NARRATIVE_SCENE_TEMPLATES, buildDriftKeyframes, createNarrativeScene } from '../src/lib/sceneNarrative.ts'
import { evaluateSceneLayer, sceneProgressFromSeconds } from '../src/lib/sceneTimeline.ts'

const assets = {
  hero: { source: '/hero.glb', type: 'model3d', name: 'Explorer' },
  plate: { source: '/space.jpg', type: 'image', name: 'Space' },
  foreground: { source: '/foreground.png', type: 'image', name: 'Rocks' },
}

test('narrative library exposes ten standard scenes plus the travel experiment', () => {
  assert.equal(NARRATIVE_SCENE_TEMPLATES.length, 11)
  assert.equal(NARRATIVE_SCENE_TEMPLATES.filter(template => !template.experimental).length, 10)
  assert.ok(NARRATIVE_SCENE_TEMPLATES.every(template => template.defaultDuration >= 10))
  assert.ok(NARRATIVE_SCENE_TEMPLATES.every(template => template.constraints.includes('continuous_motion') && template.previewPrompt && typeof template.createScene === 'function'))
})

test('narrative gallery entries expose actionable visual evaluation metadata', () => {
  const categories = new Set(['dialogue', 'character', 'world', 'object', 'transition', 'travel'])
  for (const template of NARRATIVE_SCENE_TEMPLATES) {
    assert.ok(categories.has(template.category), `${template.id} has a gallery category`)
    assert.ok(template.visualIntent.length > 20, `${template.id} has a visual intent`)
    assert.ok(template.referenceMotion.length > 20, `${template.id} has reference motion`)
    assert.ok(template.evaluationCues.length >= 3, `${template.id} has evaluation cues`)
    assert.ok(template.evaluationCues.every(cue => cue.length > 10), `${template.id} cues are reviewable`)
  }
})

test('drift keyframes keep long motion alive near the end of a shot', () => {
  const frames = buildDriftKeyframes('hero', 10, { x: 40, y: 50, scale: 1, opacity: 1, rotation: 0 }, { x: 60, y: 50, scale: 1, opacity: 1, rotation: 0 }, { bob: 1, pulse: .02 })
  assert.ok(frames.length >= 5)
  assert.notDeepEqual(frames.at(-1), frames.at(-2))
  assert.notEqual(frames.find(frame => frame.time >= 8)?.x, frames.find(frame => frame.time >= 6)?.x)
})

test('export seconds map exactly to the normalized preview timeline', () => {
  assert.equal(sceneProgressFromSeconds(0, 10), 0)
  assert.equal(sceneProgressFromSeconds(5, 10), .5)
  assert.equal(sceneProgressFromSeconds(10, 10), 1)
  assert.equal(sceneProgressFromSeconds(25, 10), 1)
})

test('the first narrative templates compile to editable 10+ second ordinary scenes', () => {
  for (const id of ['inner-thought', 'hero-arrival', 'dream-orbit']) {
    const scene = createNarrativeScene(id, assets)
    assert.ok(scene.duration >= 10)
    assert.ok(scene.layers.some(layer => layer.id === 'hero'))
    assert.ok(scene.layers.some(layer => layer.type === 'camera'))
    const hero = scene.layers.find(layer => layer.id === 'hero')
    assert.ok(hero?.animation.keyframes?.length >= 3)
    const early = evaluateSceneLayer(hero, scene.duration * .1)
    const late = evaluateSceneLayer(hero, scene.duration * .9)
    assert.notDeepEqual(early, late)
  }
})

test('every standard template has its own editable narrative composition', () => {
  for (const template of NARRATIVE_SCENE_TEMPLATES.filter(template => !template.experimental)) {
    const scene = createNarrativeScene(template.id, { ...assets, prop: assets.hero })
    assert.equal(scene.name, template.title)
    assert.ok(scene.layers.some(layer => layer.type === 'camera'))
    assert.ok(scene.layers.some(layer => layer.animation.keyframes?.length >= 3 || layer.animation.spin))
    const animated = scene.layers.filter(layer => layer.type !== 'camera' && layer.animation.keyframes?.length)
    assert.ok(animated.some(layer => JSON.stringify(evaluateSceneLayer(layer, scene.duration * .1)) !== JSON.stringify(evaluateSceneLayer(layer, scene.duration * .9))))
  }
})

test('run travel uses multi-plane strip motion without claiming a rigged run', () => {
  const scene = createNarrativeScene('run-travel-parallax', assets)
  const background = scene.layers.find(layer => layer.id === 'plate')
  const foreground = scene.layers.find(layer => layer.id === 'foreground')
  const hero = scene.layers.find(layer => layer.id === 'hero')
  assert.equal(scene.duration, 12)
  assert.equal(background?.strip?.speed, 12)
  assert.equal(background?.strip?.direction, 'left')
  assert.equal(background?.strip?.seamOccluder?.enabled, true)
  assert.equal(foreground?.strip?.speed, 58)
  assert.equal(foreground?.strip?.direction, 'left')
  assert.equal(hero?.animation.clip, undefined)
})

test('a plate must be explicitly marked loop-ready before advanced world tools may use it', () => {
  const ordinary = createNarrativeScene('run-travel-parallax', assets)
  const verified = createNarrativeScene('run-travel-parallax', { ...assets, plate: { ...assets.plate, seamlessHorizontal: true } })
  assert.equal(ordinary.layers.find(layer => layer.id === 'plate')?.seamlessHorizontal, false)
  assert.equal(verified.layers.find(layer => layer.id === 'plate')?.seamlessHorizontal, true)
})

test('run travel scrolls the world opposite the requested facing', () => {
  const left = createNarrativeScene('run-travel-parallax', { ...assets, controls: { direction: 'left' } })
  assert.equal(left.layers.find(layer => layer.id === 'plate')?.strip?.direction, 'right')
  assert.equal(left.layers.find(layer => layer.id === 'foreground')?.strip?.direction, 'right')
})

test('narrative controls alter the editable template scene without adding hidden layers', () => {
  const plain = createNarrativeScene('inner-thought', assets)
  const tuned = createNarrativeScene('inner-thought', { ...assets, controls: { mood: 'dreamy', intensity: 3, palette: 'neon', voiceSpace: 'left', camera: 'push', direction: 'right' } })
  const plainHero = plain.layers.find(layer => layer.id === 'hero')
  const tunedHero = tuned.layers.find(layer => layer.id === 'hero')
  assert.equal(tuned.layers.length, plain.layers.length)
  assert.equal(tunedHero?.transform.x, plainHero.transform.x + 14)
  assert.ok((tunedHero?.effects?.glow ?? 0) > (plainHero?.effects?.glow ?? 0))
  assert.ok((tunedHero?.effects?.saturation ?? 0) > (plainHero?.effects?.saturation ?? 0))
  assert.deepEqual({ templateId: tuned.narrative?.templateId, controls: tuned.narrative?.controls }, { templateId: 'inner-thought', controls: { mood: 'dreamy', intensity: 3, palette: 'neon', voiceSpace: 'left', camera: 'push', direction: 'right' } })
})

test('narrative provenance records the assigned assets and compiled direction', () => {
  const next = createNarrativeScene('inner-thought', { hero: { source: '/hero.glb', type: 'model3d', name: 'Explorer' }, plate: { source: '/space.png', type: 'image', name: 'Space' }, controls: { mood: 'dreamy', camera: 'drift' } })
  assert.deepEqual(next.narrative?.assets?.map(asset => asset.slot), ['hero', 'plate'])
  assert.match(next.narrative?.prompt ?? '', /Inner thought/)
  assert.match(next.narrative?.prompt ?? '', /mood: dreamy/)
})

test('narrative provenance serializes the gallery metadata used for evaluation', () => {
  const template = NARRATIVE_SCENE_TEMPLATES.find(item => item.id === 'run-travel-parallax')
  const scene = createNarrativeScene('run-travel-parallax', assets)
  assert.equal(scene.narrative?.category, template.category)
  assert.equal(scene.narrative?.visualIntent, template.visualIntent)
  assert.equal(scene.narrative?.referenceMotion, template.referenceMotion)
  assert.deepEqual(scene.narrative?.evaluationCues, template.evaluationCues)
  assert.notEqual(scene.narrative?.evaluationCues, template.evaluationCues)
  assert.doesNotThrow(() => JSON.stringify(scene))
})
