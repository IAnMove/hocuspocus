import assert from 'node:assert/strict'
import test from 'node:test'
import {
  applyStudioAudioSubmitParams,
  applyStudioSfxSubmitParams,
  applyStudioSpeechSubmitParams,
} from '../src/stores/studioAudioSubmit.ts'

test('SFX submit uses MMAudio prompt and does not keep leftover lyrics', () => {
  const params = applyStudioSfxSubmitParams(
    { model_type: 'mmaudio_v2', prompt: 'old lyrics', MMAudio_prompt: 'whoosh' },
    { generationMode: 'audio', audioSubMode: 'sfx', durationSeconds: 8 },
  )
  assert.equal(params.prompt, 'whoosh')
  assert.equal(params.sfx_mode, true)
  assert.equal(params._mmaudio_variant, 'v2')
  assert.equal(params.duration_seconds, 8)
})

test('Speech submit maps character names to Speaker N and keeps guides', () => {
  const params = applyStudioSpeechSubmitParams(
    { prompt: 'Alice: hello\nBob: hi', model_type: 'multitalk' },
    {
      generationMode: 'audio',
      audioSubMode: 'speech',
      durationSeconds: 20,
      ttsVoiceCount: 2,
      ttsVoices: [
        { name: 'Alice', path: '/voices/a.wav' },
        { name: 'Bob', path: '/voices/b.wav' },
      ],
      modelOptions: { audio_only: true, duration_slider: { default: 0, max: 600 } },
    },
  )
  assert.equal(params._tts_original_prompt, 'Alice: hello\nBob: hi')
  assert.equal(params.prompt, 'Speaker 1: hello\nSpeaker 2: hi')
  assert.equal(params.audio_guide, '/voices/a.wav')
  assert.equal(params.audio_guide2, '/voices/b.wav')
  assert.equal(params.duration_seconds, 20)
  assert.equal(params.sliding_window_size, undefined)
})

test('audio dispatcher stamps sub-mode and leaves video untouched', () => {
  const video = applyStudioAudioSubmitParams(
    { prompt: 'shot' },
    {
      generationMode: 'video',
      audioSubMode: 'speech',
      durationSeconds: 4,
      ttsVoiceCount: 0,
      ttsVoices: [],
      musicDescription: '',
      musicInstrumental: false,
    },
  )
  assert.equal(video._audio_sub_mode, undefined)
  const speech = applyStudioAudioSubmitParams(
    { prompt: 'Alice: hi', model_type: 'multitalk' },
    {
      generationMode: 'audio',
      audioSubMode: 'speech',
      durationSeconds: 4,
      ttsVoiceCount: 1,
      ttsVoices: [{ name: 'Alice' }],
      musicDescription: '',
      musicInstrumental: false,
    },
  )
  assert.equal(speech._audio_sub_mode, 'speech')
})

test('speech submit accepts AppState-shaped null voice paths and duration slider', () => {
  const params = applyStudioSpeechSubmitParams(
    { prompt: 'Alice: hello', model_type: 'multitalk', num_inference_steps: 30 },
    {
      generationMode: 'audio',
      audioSubMode: 'speech',
      durationSeconds: 0,
      ttsVoiceCount: 1,
      ttsVoices: [{ name: 'Alice', path: null }],
      modelOptions: {
        audio_only: true,
        duration_slider: null,
        default_num_inference_steps: null,
      },
    },
  )
  assert.equal(params.prompt, 'Speaker 1: hello')
  assert.equal(params.audio_guide, undefined)
  assert.equal(params.duration_seconds, 600)
  assert.equal(params.num_inference_steps, 0)
})
