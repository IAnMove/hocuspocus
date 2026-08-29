import assert from 'node:assert/strict'
import test from 'node:test'
import { recipeAudioGenerationParams } from '../src/lib/sceneRecipeAssets.ts'
import { parseSceneRecipe, recipeAudioDuration, withResolvedSources } from '../src/lib/sceneRecipe.ts'

test('recipe speech uses the proven HocusPocus voice-generation contract', () => {
  const params = recipeAudioGenerationParams({
    id: 'luma-line', kind: 'speech', prompt: 'Hola desde la plaza.',
  }, 4.2, 'episode-room')
  assert.equal(params.model_type, 'qwen3_tts_voicedesign')
  assert.equal(params.generation_mode, 'audio')
  assert.equal(params._audio_sub_mode, 'speech')
  assert.equal(params.duration_seconds, 4.2)
  assert.equal(params.workspace, 'episode-room')
  assert.equal(params.video_length, 0)
})

test('recipe SFX uses MMAudio with an isolated non-dialogue prompt', () => {
  const params = recipeAudioGenerationParams({
    id: 'antenna', kind: 'sfx', prompt: 'Three soft antenna chirps.',
  }, 8, 'default')
  assert.equal(params.model_type, 'mmaudio_v2')
  assert.equal(params.MMAudio_prompt, 'Three soft antenna chirps.')
  assert.match(params.MMAudio_neg_prompt, /speech/)
  assert.equal(params.sfx_mode, true)
})

test('generic generated audio follows the SFX engine while keeping its recipe kind', () => {
  const params = recipeAudioGenerationParams({
    id: 'room-tone', kind: 'audio', prompt: 'Soft winter square ambience.',
  }, 6, 'default')
  assert.equal(params.model_type, 'mmaudio_v2')
  assert.equal(params._audio_sub_mode, 'sfx')
  assert.equal(params.sfx_mode, true)
})

test('resolved audio filenames become durable recipe sources', () => {
  const recipe = {
    version: 1,
    name: 'audio-scene',
    assets: [],
    audio: [{ id: 'voice', kind: 'speech', prompt: 'A line' }],
    scene: { duration: 3, layers: [] },
  }
  const stored = withResolvedSources(recipe, { voice: 'voice-result.wav' })
  assert.equal(stored.audio[0].source, 'voice-result.wav')
  assert.equal(recipe.audio[0].source, undefined)
})

test('recipe audio generation refuses an unresolved silent prompt', () => {
  assert.throws(
    () => recipeAudioGenerationParams({ id: 'voice', kind: 'speech' }, 3, 'default'),
    /needs a prompt or an existing source/,
  )
})

test('auto-generated episode speech is capped at the spoken shot, not scene.duration', () => {
  const layers = [
    { id: 'camera', type: 'camera', cameraPreset: 'camera-locked' },
    { id: 'hero', type: 'image', asset: 'hero-art' },
    { id: 'mouth-wide', name: 'Mouth wide', type: 'overlay', asset: 'mouth-art', faceBinding: { poseLayerId: 'hero', role: 'mouth', state: 'wide' } },
  ]
  const recipe = parseSceneRecipe({
    version: 1,
    name: 'episode-hold-then-line',
    assets: [
      { id: 'hero-art', kind: 'image', source: 'hero.png' },
      { id: 'mouth-art', kind: 'image', source: 'mouth.png' },
    ],
    audio: [
      { id: 'voice-snowman', kind: 'speech', prompt: 'El timbre de verdad está detrás del muñeco de nieve.' },
    ],
    dialogueBeats: [
      { id: 'beat-snowman', text: 'El timbre de verdad está detrás del muñeco de nieve.', start: 0.3, end: 7.6, mouthLayerIds: ['mouth-wide'], audioTrackId: 'voice-snowman' },
    ],
    shots: [
      { name: 'hold', duration: 6, audioTrackIds: [], dialogueBeatIds: [], layers },
      { name: 'snowman', duration: 9, audioTrackIds: ['voice-snowman'], dialogueBeatIds: ['beat-snowman'], layers },
    ],
    scene: { width: 1280, height: 720, fps: 30, duration: 8, layers },
  })
  const seconds = recipeAudioDuration(recipe, 'voice-snowman')
  assert.equal(seconds, 9)
  const params = recipeAudioGenerationParams(recipe.audio[0], seconds, 'episode-room')
  assert.equal(params.duration_seconds, 9)
  assert.notEqual(params.duration_seconds, recipe.scene.duration)
})
