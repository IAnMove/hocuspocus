import assert from 'node:assert/strict'
import test from 'node:test'
import { recipeAudioGenerationParams } from '../src/lib/sceneRecipeAssets.ts'
import { withResolvedSources } from '../src/lib/sceneRecipe.ts'

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
