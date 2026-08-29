import assert from 'node:assert/strict'
import test from 'node:test'
import { characterKitRecipeInventory, createCharacterKit, mountCharacterKitLayers } from '../src/lib/characterKit.ts'
import { composeCharacterKitLook, lockFaceRigMouthPlacement } from '../src/lib/characterKitFaceRig.ts'
import { compileRecipeShot, listRecipeShots, parseSceneRecipe, recipeAudioDuration } from '../src/lib/sceneRecipe.ts'
import { evaluateSceneLayer } from '../src/lib/sceneTimeline.ts'

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
      animation: layer.animation,
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
  assert.equal(recipe.scene.duration, 8)
  assert.equal(shots[3].duration, 9)
  assert.equal(recipeAudioDuration(recipe, 'voice-luma-2'), 9)
})

test('mini South Park-style cutout dialogue locks mouths and scopes speech per shot', () => {
  const look = composeCharacterKitLook({
    name: 'Luma',
    traits: 'beanie, pigtails',
    stylePrompt: 'flat paper-cut collage, torn paper edges, thick uneven black outline, layered construction paper',
  })
  const lumaKit = lockFaceRigMouthPlacement({
    ...luma(),
    lookNotes: look,
    mouth: {
      closed: asset('luma-mouth-closed', '/api/v1/file/luma-mouth-closed-v1.png'),
      small: asset('luma-mouth-small', '/api/v1/file/luma-mouth-open-v2.png'),
      wide: asset('luma-mouth-wide', '/api/v1/file/luma-mouth-wide-v1.png'),
      round: asset('luma-mouth-round', '/api/v1/file/luma-mouth-round-v1.png'),
    },
  }, 'base', { offsetX: 0, offsetY: -22, scale: .05, rotation: 0 })
  const brinKit = lockFaceRigMouthPlacement({
    ...brin(),
    mouth: {
      closed: asset('brin-mouth-closed', '/api/v1/file/brin-mouth-closed-v1.cleanup-80de8898.png'),
      small: asset('brin-mouth-small', '/api/v1/file/brin-mouth-small-gen.cleanup-d94f04ef.png'),
      wide: asset('brin-mouth-wide', '/api/v1/file/brin-mouth-wide-v1.cleanup-12df84c6.png'),
      round: asset('brin-mouth-round', '/api/v1/file/brin-mouth-round-v1.cleanup-40f991ad.png'),
    },
    eyes: { blink: asset('brin-blink', '/api/v1/file/brin-blink-eyes-v1.cleanup-1ed2cbfe.png') },
  }, 'reaction', { offsetX: 0, offsetY: -18, scale: .05, rotation: 0 })

  const lumaLayers = recipeLayers(lumaKit, 'base', { x: 32, y: 58, scale: .62, opacity: 1, rotation: 0 })
  const lumaSmall = recipeLayers(lumaKit, 'base', { x: 32, y: 58, scale: .4, opacity: 1, rotation: 0 })
  const brinLayers = recipeLayers(brinKit, 'reaction', { x: 68, y: 58, scale: .62, opacity: 1, rotation: 0 })
  const lumaMouth = lumaLayers.find(layer => layer.id === 'kit-luma-mouth-wide')
  const lumaMouthSmall = lumaSmall.find(layer => layer.id === 'kit-luma-mouth-wide')
  assert.equal(lumaMouth.transform.y, 58 + (-22) * .62)
  assert.equal(lumaMouthSmall.transform.y, 58 + (-22) * .4)
  assert.notEqual(lumaMouth.transform.y, lumaMouthSmall.transform.y)
  const mouthStates = ['closed', 'small', 'wide', 'round']
  for (const state of mouthStates) {
    const layer = lumaLayers.find(item => item.id === `kit-luma-mouth-${state}`)
    assert.equal(layer.transform.y, lumaMouth.transform.y)
    assert.equal(layer.transform.scale, .62 * .05)
  }

  const lumaMouthIds = lumaLayers.filter(layer => layer.faceBinding?.role === 'mouth').map(layer => layer.id)
  const brinMouthIds = brinLayers.filter(layer => layer.faceBinding?.role === 'mouth').map(layer => layer.id)
  const recipe = parseSceneRecipe({
    version: 1,
    name: 'cafeteria-snow-menu',
    record: false,
    save: false,
    assets: [
      { id: 'square', kind: 'image', source: '/api/v1/file/luma-snow-square-plate-v1.png' },
      { id: 'luma-base', kind: 'image', source: lumaKit.base.source },
      { id: 'brin-reaction', kind: 'image', source: brinKit.poses.reaction.source },
    ],
    audio: [
      { id: 'voice-luma-menu', kind: 'speech', source: 'luma-menu.wav', prompt: 'Hoy el menú es solo nieve.', model: 'qwen3_tts_voicedesign' },
      { id: 'voice-brin-tray', kind: 'speech', source: 'brin-tray.wav', prompt: 'Eso es el patio.', model: 'qwen3_tts_voicedesign' },
      { id: 'voice-luma-done', kind: 'speech', source: 'luma-done.wav', prompt: 'Entonces ya comimos.', model: 'qwen3_tts_voicedesign' },
    ],
    dialogueBeats: [
      { id: 'beat-luma-menu', text: 'Hoy el menú es solo nieve.', start: 0.3, end: 3.6, mouthLayerIds: lumaMouthIds, audioTrackId: 'voice-luma-menu', confidence: 'known-text' },
      { id: 'beat-brin-tray', text: 'Eso es el patio.', start: 0.3, end: 2.8, mouthLayerIds: brinMouthIds, audioTrackId: 'voice-brin-tray', confidence: 'known-text' },
      { id: 'beat-luma-done', text: 'Entonces ya comimos.', start: 0.3, end: 3.2, mouthLayerIds: lumaMouthIds, audioTrackId: 'voice-luma-done', confidence: 'known-text' },
    ],
    shots: [
      { name: 'hold', duration: 4, audioTrackIds: [], dialogueBeatIds: [], layers: brinLayers },
      { name: 'luma-menu', duration: 5, audioTrackIds: ['voice-luma-menu'], dialogueBeatIds: ['beat-luma-menu'], layers: lumaLayers },
      { name: 'brin-tray', duration: 4, audioTrackIds: ['voice-brin-tray'], dialogueBeatIds: ['beat-brin-tray'], layers: brinLayers },
      { name: 'luma-done', duration: 5, audioTrackIds: ['voice-luma-done'], dialogueBeatIds: ['beat-luma-done'], layers: lumaLayers },
    ],
    scene: { width: 1280, height: 720, fps: 30, duration: 5, mood: 'calm', palette: 'cool', intensity: 2, layers: lumaLayers },
  })

  const shots = listRecipeShots(recipe)
  assert.equal(shots.length, 4)
  assert.equal(shots.reduce((sum, shot) => sum + shot.duration, 0), 18)
  const silent = compileRecipeShot(recipe, shots[0], {}, filename => filename)
  assert.equal(silent.audioTracks, undefined)
  assert.equal(silent.dialogueBeats, undefined)
  const silentMouths = silent.layers.filter(layer => layer.faceBinding?.role === 'mouth')
  assert.ok(silentMouths.length >= 4)
  for (const layer of silentMouths) {
    const rest = evaluateSceneLayer(layer, 0)
    assert.equal(rest.x, layer.transform.x)
    assert.equal(rest.y, layer.transform.y)
    assert.equal(rest.scale, layer.transform.scale)
    assert.equal(rest.opacity, layer.faceBinding.state === 'closed' ? 1 : 0)
  }
  const lumaLine = compileRecipeShot(recipe, shots[1], {}, filename => filename)
  assert.deepEqual(lumaLine.audioTracks.map(track => track.id), ['voice-luma-menu'])
  assert.deepEqual(lumaLine.dialogueBeats.map(beat => beat.id), ['beat-luma-menu'])
  assert.ok(lumaLine.layers.filter(layer => layer.faceBinding?.role === 'mouth').every(layer => layer.id.startsWith('kit-luma-mouth-')))
  assert.ok(lumaLine.layers.some(layer => layer.animation?.keyframes?.length > 1))
  const mountedWide = lumaLayers.find(layer => layer.id === 'kit-luma-mouth-wide')
  const spokenWide = lumaLine.layers.find(layer => layer.id === 'kit-luma-mouth-wide')
  assert.ok(spokenWide.animation.keyframes.length > 1)
  assert.ok(spokenWide.animation.keyframes.every(frame => (
    frame.x === mountedWide.transform.x
    && frame.y === mountedWide.transform.y
    && frame.scale === mountedWide.transform.scale
  )))
  assert.notEqual(spokenWide.animation.keyframes[0].x, 50)
  assert.notEqual(spokenWide.animation.keyframes[0].scale, 1)
  const brinLine = compileRecipeShot(recipe, shots[2], {}, filename => filename)
  assert.deepEqual(brinLine.audioTracks.map(track => track.id), ['voice-brin-tray'])
  assert.equal(brinLine.layers.some(layer => layer.id.includes('luma')), false)
  assert.ok(brinLine.layers.filter(layer => layer.faceBinding?.role === 'mouth').every(layer => layer.id.startsWith('kit-brin-mouth-')))
})
