import assert from 'node:assert/strict'
import test from 'node:test'
import { sceneToRecipe } from '../src/lib/sceneToRecipe.ts'
import { compileSceneRecipe, parseSceneRecipe } from '../src/lib/sceneRecipe.ts'
import { createNarrativeScene } from '../src/lib/sceneNarrative.ts'

const sceneFixture = () => ({
  version: 1,
  name: 'edited-shot',
  width: 1280,
  height: 720,
  fps: 30,
  duration: 6,
  layers: [{
    id: 'hero',
    name: 'Hero',
    type: 'image',
    source: '/assets/hero.png',
    visible: false,
    locked: true,
    z: 20,
    fill: false,
    parallax: 1,
    transform: { x: 48, y: 52, scale: 0.8, opacity: 1, rotation: 0 },
    effects: { blur: 7, brightness: 1.1 },
    animation: {
      start: { x: 20, y: 50, scale: 0.7, opacity: 0, rotation: 0 },
      end: { x: 80, y: 50, scale: 1, opacity: 1, rotation: 0 },
      keyframes: [
        { id: 'a', time: 0, x: 20, y: 50, scale: 0.7, opacity: 0, rotation: 0, curve: 'ease' },
        { id: 'b', time: 2, x: 45, y: 49, scale: 0.9, opacity: 1, rotation: 1, curve: 'hold' },
        { id: 'c', time: 6, x: 80, y: 50, scale: 1, opacity: 1, rotation: 0, curve: 'linear' },
      ],
      duration: 6,
      curve: 'ease',
      spin: false,
    },
  }],
})

test('sceneToRecipe preserves authored visibility, blur and keyframe tracks', () => {
  const scene = sceneFixture()
  const recipe = sceneToRecipe(scene)
  const layer = recipe.scene.layers[0]
  assert.equal(layer.visible, false)
  assert.equal(layer.effects.blur, 7)
  assert.deepEqual(layer.animation.keyframes, scene.layers[0].animation.keyframes)
  assert.equal(recipe.assets[0].source, '/assets/hero.png')
  assert.equal(layer.asset, recipe.assets[0].id)
})

test('sceneToRecipe is pure and copies nested authored state', () => {
  const scene = sceneFixture()
  const recipe = sceneToRecipe(scene)
  const sourceFrame = scene.layers[0].animation.keyframes[0]
  const recipeFrame = recipe.scene.layers[0].animation.keyframes[0]
  recipeFrame.x = 999
  recipe.scene.layers[0].effects.blur = 0
  assert.equal(sourceFrame.x, 20)
  assert.equal(scene.layers[0].effects.blur, 7)
})

test('a serialized edited scene survives parser and compiler round trip', () => {
  const authored = sceneFixture()
  authored.layers.push({
    ...authored.layers[0], id: 'plate', name: 'Plate', source: '/assets/plate.png', visible: true,
    effects: undefined, animation: { ...authored.layers[0].animation, keyframes: undefined },
  })
  const recipe = parseSceneRecipe(JSON.parse(JSON.stringify(sceneToRecipe(authored))))
  const scene = compileSceneRecipe(recipe, {}, source => source)
  const hero = scene.layers.find(layer => layer.id === 'hero')
  assert.equal(hero.visible, false)
  assert.equal(hero.locked, true)
  assert.equal(hero.effects.blur, 7)
  assert.equal(hero.animation.keyframes.length, 3)
  assert.equal(hero.animation.keyframes[1].curve, 'hold')
})

test('a speaking beat round-trips with its editable mouth provenance', () => {
  const authored = sceneFixture()
  authored.layers[0].visible = true
  authored.dialogueBeats = [{ id: 'line-1', text: 'Hola mundo', start: .5, end: 3, mouthLayerIds: ['hero'], audioTrackId: 'voice', confidence: 'known-text' }]
  const recipe = parseSceneRecipe(JSON.parse(JSON.stringify(sceneToRecipe(authored))))
  const scene = compileSceneRecipe(recipe, {}, source => source)
  assert.deepEqual(scene.dialogueBeats, authored.dialogueBeats)
  scene.dialogueBeats[0].mouthLayerIds.push('copy-only')
  assert.deepEqual(recipe.dialogueBeats[0].mouthLayerIds, ['hero'])
})

test('pose-specific face binding survives scene serialization', () => {
  const authored = sceneFixture()
  authored.layers[0].faceBinding = { poseLayerId: 'pose-a', role: 'mouth', state: 'wide' }
  const recipe = sceneToRecipe(authored)
  assert.deepEqual(recipe.scene.layers[0].faceBinding, { poseLayerId: 'pose-a', role: 'mouth', state: 'wide' })
  recipe.scene.layers[0].faceBinding.state = 'round'
  assert.equal(authored.layers[0].faceBinding.state, 'wide')
})

test('generic audio and its generating model survive the recipe round trip', () => {
  const authored = sceneFixture()
  authored.layers[0].visible = true
  authored.audioTracks = [{
    id: 'room-tone', filename: 'snow-square-room-tone.wav', name: 'Snow square ambience',
    kind: 'audio', startTime: .25, volume: .7, prompt: 'Soft winter square ambience', model: 'mmaudio_v2',
  }]
  const recipe = parseSceneRecipe(JSON.parse(JSON.stringify(sceneToRecipe(authored))))
  const scene = compileSceneRecipe(recipe, {}, source => source)
  assert.deepEqual(scene.audioTracks, authored.audioTracks)
})

test('a real run-travel template remains a faithful recipe after compilation', () => {
  const authored = createNarrativeScene('run-travel-parallax', {
    hero: { name: 'Runner', type: 'image', source: '/assets/runner.png' },
    plate: { name: 'Station', type: 'image', source: '/assets/station.png', seamlessHorizontal: true },
    foreground: { name: 'Lamp', type: 'image', source: '/assets/lamp.png' },
    duration: 10,
  })
  const recipe = parseSceneRecipe(JSON.parse(JSON.stringify(sceneToRecipe(authored))))
  const scene = compileSceneRecipe(recipe, {}, source => source)
  const sourceRunner = authored.layers.find(layer => layer.id === 'hero')
  const runner = scene.layers.find(layer => layer.id === 'hero')
  const plate = scene.layers.find(layer => layer.id === 'plate')
  assert.deepEqual(runner.animation.keyframes, sourceRunner.animation.keyframes)
  assert.equal(plate.strip.seamOccluder.enabled, true)
  assert.equal(plate.strip.direction, 'left')
  assert.equal(plate.seamlessHorizontal, true)
})
