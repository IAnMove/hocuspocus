import test from 'node:test'
import assert from 'node:assert/strict'
import { CHARACTER_VOICE_LANGUAGES, isCharacterVoiceReady, parseCharacterVoice, type CustomCharacterVoice } from '../src/lib/characterVoice'
import { createCharacterKit, resolvedCharacterTts } from '../src/lib/characterKit'
import { generateSceneSpeechClip } from '../src/lib/sceneSpeech'

const custom: CustomCharacterVoice = { provider: 'local', model: 'qwen3_tts_base', voiceId: 'reference',
  name: 'My Spanish narrator', referenceAudio: '/api/v1/uploads/audio/recording.wav',
  transcript: 'Esta es mi voz. Hoy vamos a contar una historia.', language: 'spanish' }

test('reference voices and existing presets survive public JSON without credentials or host paths', () => {
  assert.deepEqual(parseCharacterVoice(JSON.parse(JSON.stringify(custom))), custom)
  const preset = { provider: 'local', model: 'qwen3_tts_customvoice', voiceId: 'ryan', instructions: 'Warm' }
  assert.deepEqual(parseCharacterVoice(preset), preset)
  assert.equal(isCharacterVoiceReady(undefined), true)
  for (const language of CHARACTER_VOICE_LANGUAGES) assert.equal(isCharacterVoiceReady({ ...custom, language }), true)
  assert.equal(resolvedCharacterTts({ ...createCharacterKit('Narrator'), voice: custom }).voiceName, custom.name)
  assert.equal(resolvedCharacterTts({ ...createCharacterKit('Narrator'), voice: custom }).voiceId, 'reference')
  assert.deepEqual(parseCharacterVoice({ ...custom, name: '  Narrator  ', transcript: '  Hola.  ' }),
    { ...custom, name: 'Narrator', transcript: 'Hola.' })
})

test('unfinished drafts and unsupported reference fields cannot be saved or generated', () => {
  for (const patch of [{ name: '' }, { name: ' '.repeat(10) }, { name: 'a'.repeat(121) }, { name: 12 },
    { transcript: '' }, { transcript: '\n' }, { transcript: 'a'.repeat(4001) }, { transcript: null },
    { referenceAudio: '' }, { language: 'martian' }, { language: [] }, { provider: 'remote' },
    { voiceId: 'ryan' }, { apiKey: 'not-a-secret' }, { instructions: 'unsupported by Base' }]) {
    assert.equal(isCharacterVoiceReady({ ...custom, ...patch }), false, JSON.stringify(patch))
    assert.throws(() => parseCharacterVoice({ ...custom, ...patch }))
  }
  for (const key of Object.keys(custom)) {
    const missing = { ...custom } as Record<string, unknown>
    delete missing[key]
    assert.throws(() => parseCharacterVoice(missing), key)
  }
})

test('reference URLs keep exact public roots and source workspaces; remote and ambiguous paths are rejected', () => {
  for (const referenceAudio of ['/api/v1/uploads/voice.wav', '/api/v1/uploads/audio/mi%20voz.wav',
    '/api/v1/file/assets/actors/voice.wav?workspace=original', '/api/v1/file/voice.flac?workspace=My%20Voices']) {
    assert.equal(parseCharacterVoice({ ...custom, referenceAudio })?.model, 'qwen3_tts_base')
  }
  for (const referenceAudio of ['https://example.com/voice.wav', '//example.com/voice.wav', 'blob:voice',
    'data:audio/wav;base64,AAAA', '/home/private.wav', '/api/v1/uploads/../voice.wav',
    '/api/v1/uploads/%2e%2e/voice.wav', '/api/v1/uploads/%252e%252e/voice.wav',
    '/api/v1/uploads/audio%5cvoice.wav', '/api/v1/uploads/.private/voice.wav',
    '/api/v1/uploads/voice.wav?token=example', '/api/v1/uploads/voice.wav#fragment',
    '/api/v1/uploads/voice.wav?', '/api/v1/uploads/voice%00.wav', '/api/v1/uploads/%ZZ.wav',
    '/api/v1/uploads/voice.json', '/api/v1/uploads/voice.webm', '/api/v1/uploads/voice wav.wav', '/api/v1/uploads//voice.wav',
    '/api/v1/file/voice.wav', '/api/v1/file/voice.wav?workspace=', '/api/v1/file/voice.wav?workspace=..',
    '/api/v1/file/voice.wav?workspace=one&workspace=two', '/api/v1/file/voice.wav?workspace=one&key=example',
    '/api/v1/file/voice.wav?workspace=%ZZ', '/api/v1/file/voice.wav?workspace=%FF']) {
    assert.throws(() => parseCharacterVoice({ ...custom, referenceAudio }), referenceAudio)
  }
})

test('Base generation adopts the exact reference from its source workspace and outputs into the scene workspace', async () => {
  const requests: Record<string, unknown>[] = [], adopted: Record<string, unknown>[] = []
  const voice = { ...custom, referenceAudio: '/api/v1/file/assets/narrator.wav?workspace=Voice%20Library' }
  const saved = JSON.stringify(voice)
  const result = await generateSceneSpeechClip({ model: voice.model, voice, prompt: 'Nueva frase.', durationSeconds: 5, workspace: 'episode' }, {
    adoptAudio: async params => { adopted.push(params); return { filename: 'narrator.wav', path: '/server/Voice Library/assets/narrator.wav', url: voice.referenceAudio } },
    submitGeneration: async params => { requests.push(params); return { job_id: 'owned-base', status: 'queued' } },
    fetchJobStatus: async () => ({ status: 'completed', output_files: ['line.wav'] } as never),
  })
  assert.deepEqual(adopted, [{ audio_path: voice.referenceAudio, workspace: 'Voice Library' }])
  assert.equal(requests.length, 1)
  assert.equal(requests[0].model_type, 'qwen3_tts_base')
  assert.equal(requests[0].model_mode, 'spanish')
  assert.equal(requests[0].audio_prompt_type, 'A')
  assert.equal(requests[0].audio_guide, '/server/Voice Library/assets/narrator.wav')
  assert.equal(requests[0].alt_prompt, custom.transcript)
  assert.equal(requests[0].workspace, 'episode')
  assert.equal(requests[0].prompt, 'Nueva frase.')
  assert.equal(result.filename, 'line.wav')
  assert.equal(JSON.stringify(voice), saved, 'the resolved host path must never replace the reusable reference URL')
})

test('an upload is adopted from its declared root and a missing reference never queues speech', async () => {
  const adopted: Record<string, unknown>[] = []
  await assert.rejects(generateSceneSpeechClip({ model: custom.model, voice: custom, prompt: 'Hello', durationSeconds: 5, workspace: 'episode' }, {
    adoptAudio: async params => { adopted.push(params); throw new Error('Media file not found') },
    submitGeneration: async () => { assert.fail('Must not generate with a missing reference') },
    fetchJobStatus: async () => { assert.fail('Must not poll') },
  }), /Media file not found/)
  assert.deepEqual(adopted, [{ audio_path: custom.referenceAudio, workspace: 'episode' }])
})

test('cancelling while resolving a reference never submits an unwanted generation', async () => {
  const abort = new AbortController()
  await assert.rejects(generateSceneSpeechClip({ model: custom.model, voice: custom, prompt: 'Hello', durationSeconds: 5, signal: abort.signal }, {
    adoptAudio: async () => { abort.abort(); return { filename: 'voice.wav', path: '/server/voice.wav', url: custom.referenceAudio } },
    submitGeneration: async () => { assert.fail('Must not submit after cancelling') },
    fetchJobStatus: async () => { assert.fail('Must not poll') },
  }), /abort/i)
})
