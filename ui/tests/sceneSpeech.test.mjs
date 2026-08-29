import assert from 'node:assert/strict'
import test from 'node:test'
import { generateSceneSpeechClip } from '../src/lib/sceneSpeech.ts'

test('speech clip generation rejects an empty prompt without submitting a job', async () => {
  let submitted = false
  await assert.rejects(() => generateSceneSpeechClip({
    prompt: '   ',
    model: 'kugelaudio_0_open',
    durationSeconds: 3,
  }, {
    submitGeneration: async () => { submitted = true; return { job_id: 'job', status: 'queued' } },
    fetchJobStatus: async () => ({ status: 'completed', output_files: ['line.wav'] }),
  }), /Write a line of dialogue first/)
  assert.equal(submitted, false)
})

test('speech clip generation waits for a completed audio output', async () => {
  const statuses = [
    { status: 'running', output_files: [] },
    { status: 'completed', output_files: ['notes.txt', 'line.wav'] },
  ]
  const clip = await generateSceneSpeechClip({
    prompt: 'The square is frozen.',
    model: 'kugelaudio_0_open',
    durationSeconds: 3,
    pollMs: 1,
  }, {
    now: () => 0,
    wait: async () => undefined,
    submitGeneration: async params => {
      assert.equal(params.generation_mode, 'audio')
      assert.equal(params._audio_sub_mode, 'speech')
      return { job_id: 'job-1', status: 'queued' }
    },
    fetchJobStatus: async () => statuses.shift() ?? { status: 'failed', output_files: [] },
  })
  assert.deepEqual(clip, { filename: 'line.wav', jobId: 'job-1', model: 'kugelaudio_0_open', prompt: 'The square is frozen.' })
})
