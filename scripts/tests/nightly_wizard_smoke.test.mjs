import assert from 'node:assert/strict'
import test from 'node:test'

import { evaluateSmokeSongFidelity, normalizeSmokeBaseUrl, runMediaSmoke, validateSmokeOptIn } from '../nightly_wizard_smoke.mjs'

test('media smoke is fail-closed behind GPU, URL, and confirmation controls', () => {
  assert.equal(normalizeSmokeBaseUrl(' http://127.0.0.1:8000/ '), 'http://127.0.0.1:8000')
  assert.throws(() => normalizeSmokeBaseUrl('file:///tmp/hocuspocus'), /http:\/\/ or https:\/\//)
  assert.throws(() => validateSmokeOptIn({
    runGpu: true, runExternal: false, baseUrl: 'http://127.0.0.1:8000',
  }), /HOCUSPOCUS_SMOKE_CONFIRM=GENERATE_REAL_MEDIA/)
  assert.equal(validateSmokeOptIn({
    runGpu: true, runExternal: false, baseUrl: 'http://127.0.0.1:8000', confirm: 'GENERATE_REAL_MEDIA',
  }), 'http://127.0.0.1:8000')
})

test('simulated media smoke rejects a valid-looking song with the wrong language or subject', () => {
  const failed = evaluateSmokeSongFidelity({
    lyrics: '[Verse]\nThe server fights through the night.\n[Chorus]\nWe sing for proprietary software.',
    lyricsLanguage: 'Español', requiredTerms: ['sysadmin', 'red'],
  })
  assert.equal(failed.ok, false)
  assert.equal(failed.languageMismatch, true)
  assert.deepEqual(failed.missingTerms, ['sysadmin', 'red'])

  const passed = evaluateSmokeSongFidelity({
    lyrics: '[Verse]\nEn la red despierta el sysadmin.\n[Chorus]\nLa noche y el código cantan.',
    lyricsLanguage: 'Español', requiredTerms: ['sysadmin', 'red'],
  })
  assert.equal(passed.ok, true)
})

test('simulated media smoke ignores a protected foreign-language refrain when scoring the song language', () => {
  const report = evaluateSmokeSongFidelity({
    lyrics: '[Verse]\nEn la red despierta el sysadmin y la noche canta.\n[Chorus]\nThe server fights through the night and we sing for our network.',
    lyricsLanguage: 'Español',
    protectedSegments: ['The server fights through the night and we sing for our network.'],
  })
  assert.equal(report.ok, true)
  assert.equal(report.languageMismatch, false)
})

test('media smoke preserves project cue output task and pipeline identities', async () => {
  let revision = 0
  const calls = []
  const fetchImpl = async (url, options) => {
    const route = new URL(url).pathname
    calls.push(`${options.method} ${route}`)
    const request = options.body ? JSON.parse(options.body) : null
    let payload
    if (options.method === 'GET' && route === '/api/v1/stories/library') {
      payload = { version: 2, revision, activeId: '', projects: {} }
    } else if (options.method === 'PUT' && route === '/api/v1/stories/library') {
      revision += 1
      payload = { ...request.library, revision }
    } else if (options.method === 'POST' && route === '/api/v1/generate') {
      assert.equal(request.instrumental, false)
      assert.equal(request.model_type, 'ace_step_v1_5_xl_sft_lm_4b')
      assert.equal(request.generation_mode, 'audio')
      assert.equal(request.video_length, 0)
      payload = { job_id: 'song-job', task_id: 'task-song', root_task_id: 'task-song', status: 'queued' }
    } else if (options.method === 'GET' && route === '/api/v1/status/song-job') {
      payload = { status: 'completed', task_id: 'task-song', root_task_id: 'task-song', output_files: ['himno.wav'] }
    } else if (options.method === 'POST' && route === '/api/v1/audio/analyze') {
      payload = { bpm: 112, lyrics: request.lyrics_hint, beats: [0, .5, 1] }
    } else if (options.method === 'POST' && route === '/api/v1/audio/plan-structure') {
      payload = { clips: [{ start: 0, end: 5 }] }
    } else if (options.method === 'POST' && route === '/api/v1/director/pipeline/start') {
      assert.equal(request.pipeline_type, 'music_video')
      payload = { pipeline_id: 'pipeline-smoke' }
    } else if (options.method === 'GET' && route === '/api/v1/director/pipeline/pipeline-smoke') {
      payload = { status: 'completed', output_files: ['videoclip.mp4'] }
    } else {
      throw new Error(`Unexpected ${options.method} ${route}`)
    }
    return { ok: true, status: 200, async json() { return payload } }
  }

  const result = await runMediaSmoke({
    baseUrl: 'http://127.0.0.1:8000', workspace: 'nightly-smoke',
    runGpu: true, runExternal: false, confirm: 'GENERATE_REAL_MEDIA',
    fetchImpl, timeoutMs: 2_000, pollIntervalMs: 0,
  })
  assert.equal(result.songStatus, 'completed')
  assert.equal(result.pipelineStatus, 'completed')
  assert.equal(result.identifiers.projectIds.length, 1)
  assert.equal(result.identifiers.cueIds.length, 1)
  assert.deepEqual(result.identifiers.taskIds, ['task-song'])
  assert.deepEqual(result.identifiers.pipelineIds, ['pipeline-smoke'])
  assert.deepEqual(result.identifiers.outputIds, ['himno.wav', 'videoclip.mp4'])
  assert.equal(result.semantic.ok, true)
  assert.equal(calls.filter(call => call === 'PUT /api/v1/stories/library').length, 3)
})
