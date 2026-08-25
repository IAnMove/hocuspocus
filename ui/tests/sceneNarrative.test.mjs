import assert from 'node:assert/strict'
import test from 'node:test'
import { NARRATIVE_SCENE_TEMPLATES, buildDriftKeyframes, createNarrativeScene } from '../src/lib/sceneNarrative.ts'
import { evaluateSceneLayer } from '../src/lib/sceneTimeline.ts'

const assets = {
  hero: { source: '/hero.glb', type: 'model3d', name: 'Explorer' },
  plate: { source: '/space.jpg', type: 'image', name: 'Space' },
  foreground: { source: '/foreground.png', type: 'image', name: 'Rocks' },
}

test('narrative library exposes ten standard scenes plus the travel experiment', () => {
  assert.equal(NARRATIVE_SCENE_TEMPLATES.length, 11)
  assert.equal(NARRATIVE_SCENE_TEMPLATES.filter(template => !template.experimental).length, 10)
  assert.ok(NARRATIVE_SCENE_TEMPLATES.every(template => template.defaultDuration >= 10))
})

test('drift keyframes keep long motion alive near the end of a shot', () => {
  const frames = buildDriftKeyframes('hero', 10, { x: 40, y: 50, scale: 1, opacity: 1, rotation: 0 }, { x: 60, y: 50, scale: 1, opacity: 1, rotation: 0 }, { bob: 1, pulse: .02 })
  assert.ok(frames.length >= 5)
  assert.notDeepEqual(frames.at(-1), frames.at(-2))
  assert.notEqual(frames.find(frame => frame.time >= 8)?.x, frames.find(frame => frame.time >= 6)?.x)
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

test('run travel uses multi-plane strip motion without claiming a rigged run', () => {
  const scene = createNarrativeScene('run-travel-parallax', assets)
  const background = scene.layers.find(layer => layer.id === 'plate')
  const foreground = scene.layers.find(layer => layer.id === 'foreground')
  const hero = scene.layers.find(layer => layer.id === 'hero')
  assert.equal(scene.duration, 12)
  assert.equal(background?.strip?.speed, 12)
  assert.equal(foreground?.strip?.speed, 58)
  assert.equal(hero?.animation.clip, undefined)
})
