import assert from 'node:assert/strict'
import test from 'node:test'
import { characterKitRecipeInventory, createCharacterKit, mountCharacterKitLayers } from '../src/lib/characterKit.ts'
import { compileRecipeShot, listRecipeShots, parseSceneRecipe } from '../src/lib/sceneRecipe.ts'

const asset = (id, source, reviewState = 'approved', kind = 'overlay') => ({
  id, name: id, source, kind, alphaStatus: 'transparent', reviewState,
})

const luma = () => ({
  ...createCharacterKit('Luma'),
  base: { ...asset('luma-base', '/api/v1/file/luma-cutout-base-v1.png', 'approved', 'image') },
  poses: { pointing: { ...asset('luma-pointing', '/api/v1/file/luma-pointing-matched-v2-alpha.png', 'approved', 'image') } },
  mouth: {
    small: asset('luma-mouth-small', '/api/v1/file/luma-mouth-open-v2.png'),
    wide: asset('luma-mouth-wide', '/api/v1/file/luma-mouth-wide-v1.png'),
    round: asset('luma-mouth-round', '/api/v1/file/luma-mouth-round-v1.png'),
  },
  eyes: { blink: asset('luma-blink', '/api/v1/file/luma-blink-eyes-v2.png') },
  anchors: {
    base: {
      mouth: { offsetX: 0, offsetY: -19, scale: .041, rotation: 0 },
      mouthStates: { wide: { offsetX: 0, offsetY: -19, scale: .056, rotation: 0 } },
      eyes: { offsetX: 0, offsetY: -30.5, scale: .149, rotation: 0 },
    },
  },
})

const brin = () => ({
  ...createCharacterKit('Brin'),
  base: { ...asset('brin-base', '/api/v1/file/brin-cutout-base-v1.png', 'approved', 'image') },
  poses: { reaction: { ...asset('brin-reaction', '/api/v1/file/brin-cutout-reaction-v1.png', 'approved', 'image') } },
  mouth: {
    closed: asset('brin-mouth-closed', '/api/v1/file/brin-mouth-closed-v1.png', 'pending'),
    wide: asset('brin-mouth-wide', '/api/v1/file/brin-mouth-wide-v1.png', 'pending'),
  },
  eyes: { blink: asset('brin-blink', '/api/v1/file/brin-blink-eyes-v1.png', 'pending') },
})

const recipeLayers = (kit, poseId, transform) => {
  const mounted = mountCharacterKitLayers(kit, poseId, transform, 8)
  return [
    { id: 'plate', name: 'Snow square', type: 'image', source: '/api/v1/file/snow-square.png', fill: true, z: 0 },
    ...mounted.map(layer => ({
      id: layer.id,
      name: layer.name,
      type: layer.type,
      source: layer.source,
      z: layer.z,
      transform: layer.transform,
      faceBinding: layer.faceBinding,
      relationship: layer.relationship,
    })),
  ]
}

test('CharacterKit episode recipe mounts only approved pieces and isolates audio by shot', () => {
  const lumaKit = luma()
  const brinKit = brin()
  const library = { version: 1, revision: 2, activeId: 'luma', kits: { luma: lumaKit, brin: brinKit } }
  const inventory = characterKitRecipeInventory(library)
  assert.ok(inventory.some(item => item.name === 'luma/mouth/wide'))
  assert.equal(inventory.some(item => item.name.startsWith('brin/mouth/')), false)
  assert.ok(inventory.every(item => item.description.includes('APPROVED_CHARACTER_KIT')))

  const lumaLayers = recipeLayers(lumaKit, 'base', { x: 38, y: 58, scale: .7, opacity: 1, rotation: 0 })
  const lumaPointing = recipeLayers(lumaKit, 'pointing', { x: 62, y: 56, scale: .74, opacity: 1, rotation: 0 })
  const brinLayers = recipeLayers(brinKit, 'reaction', { x: 64, y: 58, scale: .68, opacity: 1, rotation: 0 })
  assert.ok(lumaLayers.some(layer => layer.id === 'kit-luma-mouth-wide'))
  assert.equal(lumaLayers.some(layer => layer.id === 'kit-luma-mouth-closed'), false)
  assert.equal(brinLayers.some(layer => layer.id.includes('mouth')), false)

  const mouthLayerIds = lumaLayers.filter(layer => layer.faceBinding?.role === 'mouth').map(layer => layer.id)
  const recipe = parseSceneRecipe({
    version: 1,
    name: 'luma-brin-frozen-bell',
    record: false,
    save: false,
    assets: [
      { id: 'square', kind: 'image', source: '/api/v1/file/snow-square.png' },
      { id: 'luma-base', kind: 'image', source: lumaKit.base.source },
      { id: 'brin-reaction', kind: 'image', source: brinKit.poses.reaction.source },
    ],
    audio: [
      { id: 'voice-luma-1', kind: 'speech', source: 'luma-bell.wav', prompt: 'La campana del patio está congelada.', model: 'qwen3_tts_voicedesign' },
      { id: 'voice-luma-2', kind: 'speech', source: 'luma-snowman.wav', prompt: 'El timbre de verdad está detrás del muñeco de nieve.', model: 'qwen3_tts_voicedesign' },
      { id: 'voice-luma-3', kind: 'speech', source: 'luma-recess.wav', prompt: 'Entonces el recreo ya ganó.', model: 'qwen3_tts_voicedesign' },
    ],
    dialogueBeats: [
      { id: 'beat-luma-1', text: 'La campana del patio está congelada.', start: 0.4, end: 6.8, mouthLayerIds, audioTrackId: 'voice-luma-1', confidence: 'known-text' },
      { id: 'beat-luma-2', text: 'El timbre de verdad está detrás del muñeco de nieve.', start: 0.3, end: 7.6, mouthLayerIds, audioTrackId: 'voice-luma-2', confidence: 'known-text' },
      { id: 'beat-luma-3', text: 'Entonces el recreo ya ganó.', start: 0.4, end: 6.2, mouthLayerIds, audioTrackId: 'voice-luma-3', confidence: 'known-text' },
    ],
    shots: [
      { name: 'square-hold', duration: 6, audioTrackIds: [], dialogueBeatIds: [], layers: brinLayers },
      { name: 'luma-bell', duration: 8, audioTrackIds: ['voice-luma-1'], dialogueBeatIds: ['beat-luma-1'], layers: lumaLayers },
      { name: 'brin-react-1', duration: 6, audioTrackIds: [], dialogueBeatIds: [], layers: brinLayers },
      { name: 'luma-snowman', duration: 9, audioTrackIds: ['voice-luma-2'], dialogueBeatIds: ['beat-luma-2'], layers: lumaPointing },
      { name: 'brin-react-2', duration: 5, audioTrackIds: [], dialogueBeatIds: [], layers: brinLayers },
      { name: 'luma-recess', duration: 8, audioTrackIds: ['voice-luma-3'], dialogueBeatIds: ['beat-luma-3'], layers: lumaLayers },
    ],
    scene: { width: 1280, height: 720, fps: 30, duration: 8, layers: lumaLayers },
  })

  const shots = listRecipeShots(recipe)
  assert.equal(shots.length, 6)
  assert.equal(shots.reduce((sum, shot) => sum + shot.duration, 0), 42)
  assert.ok(shots.every(shot => Array.isArray(shot.audioTrackIds) && Array.isArray(shot.dialogueBeatIds)))

  const silent = compileRecipeShot(recipe, shots[0], {}, filename => filename)
  assert.equal(silent.audioTracks, undefined)
  assert.equal(silent.dialogueBeats, undefined)
  assert.ok(silent.layers.some(layer => layer.id === 'kit-brin-pose-reaction'))
  assert.equal(silent.layers.some(layer => layer.id.includes('luma')), false)
  assert.equal(silent.layers.some(layer => /mouth/i.test(layer.id)), false)

  const spoken = compileRecipeShot(recipe, shots[1], {}, filename => filename)
  assert.deepEqual(spoken.audioTracks.map(track => track.id), ['voice-luma-1'])
  assert.deepEqual(spoken.dialogueBeats.map(beat => beat.id), ['beat-luma-1'])
  const lumaMouths = spoken.layers.filter(layer => layer.faceBinding?.role === 'mouth')
  assert.ok(lumaMouths.length >= 3)
  assert.ok(lumaMouths.every(layer => layer.id.startsWith('kit-luma-mouth-')))
  assert.ok(lumaMouths.some(layer => layer.animation?.keyframes?.length > 1))
  assert.equal(spoken.layers.some(layer => layer.id.includes('brin')), false)

  const pointing = compileRecipeShot(recipe, shots[3], {}, filename => filename)
  assert.ok(pointing.layers.some(layer => layer.id === 'kit-luma-pose-pointing'))
  assert.deepEqual(pointing.audioTracks.map(track => track.id), ['voice-luma-2'])
})
