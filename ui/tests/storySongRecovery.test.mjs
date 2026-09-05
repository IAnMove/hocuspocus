import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
  Event: dom.window.Event,
  CustomEvent: dom.window.CustomEvent,
})
window.matchMedia = () => ({ matches: false })

test('normalize keeps pending rows with a stable id and never remints them', async () => {
  const { normalizeStoryProject, createStoryProject, storyId } = await import('../src/features/stories/model.ts')
  const minted = 'song-keep-me'
  const base = createStoryProject('music_video')
  const pending = {
    id: minted,
    status: 'pending',
    name: '',
    source: '',
    prompt: 'metal',
    lyrics: '[Verse]\nCode',
    provider: 'local',
    model: 'ace_step_v1_5_xl_sft_lm_4b',
    durationSeconds: 30,
    createdAt: '2026-09-05T00:00:00.000Z',
  }
  const project = normalizeStoryProject({
    ...base,
    music: {
      ...base.music,
      cues: [{
        id: 'cue-1',
        kind: 'story',
        targetId: base.id,
        title: 'Theme',
        purpose: '',
        referenceSong: '',
        brief: '',
        style: 'metal',
        lyrics: '[Verse]\nCode',
        lyriaPrompt: '',
        instrumental: false,
        durationSeconds: 30,
        candidates: [pending, { source: '', prompt: 'preview' }, { id: '', source: '' }],
      }],
    },
  })
  const again = normalizeStoryProject(project)
  assert.equal(project.music.cues[0].candidates.length, 1)
  assert.equal(project.music.cues[0].candidates[0].id, minted)
  assert.equal(project.music.cues[0].candidates[0].status, 'pending')
  assert.equal(again.music.cues[0].candidates[0].id, minted)
  assert.notEqual(minted, storyId('song'))
})

test('hydrate recovers a pending song from a sidecar with matching candidate_id', async () => {
  const {
    recoverPendingStorySongs,
    storySongOutputRefFromSidecar,
  } = await import('../src/features/stories/storySongRecovery.ts')
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const pendingId = 'song-recover-1'
  const project = normalizeStoryProject({
    ...base,
    id: 'story-recover',
    title: 'Recovered anthem',
    music: {
      ...base.music,
      cues: [{
        id: 'cue-recover',
        kind: 'story',
        targetId: 'story-recover',
        title: 'Anthem',
        purpose: '',
        referenceSong: '',
        brief: '',
        style: 'metal',
        lyrics: '[Verse]\nCode',
        lyriaPrompt: '',
        instrumental: false,
        durationSeconds: 30,
        candidates: [{
          id: pendingId,
          status: 'pending',
          name: '',
          source: '',
          prompt: 'metal',
          lyrics: '[Verse]\nCode',
          provider: 'local',
          model: 'ace_step_v1_5_xl_sft_lm_4b',
          durationSeconds: 30,
          createdAt: '2026-09-05T00:00:00.000Z',
        }],
      }],
    },
  })
  const ref = storySongOutputRefFromSidecar('anthem.wav', '/api/v1/file/anthem.wav?workspace=lab', {
    origin: { project: { kind: 'story', id: project.id }, output_folder: 'lab' },
    execution: { candidate_id: pendingId, cue_id: 'cue-recover', task_id: 'task-9' },
  })
  const recovered = recoverPendingStorySongs({ [project.id]: project }, [ref])
  assert.equal(recovered.changed, true)
  const candidate = recovered.projects[project.id].music.cues[0].candidates[0]
  assert.equal(candidate.id, pendingId)
  assert.equal(candidate.status, 'ready')
  assert.equal(candidate.name, 'anthem.wav')
  assert.equal(candidate.source, '/api/v1/file/anthem.wav?workspace=lab')
  assert.equal(candidate.taskId, 'task-9')
})

test('a failed row without audio is recovered when the sidecar exists', async () => {
  const { recoverPendingStorySongs } = await import('../src/features/stories/storySongRecovery.ts')
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const failedId = 'song-failed-timeout'
  const project = normalizeStoryProject({
    ...base,
    id: 'story-failed',
    music: {
      ...base.music,
      cues: [{
        id: 'cue-failed',
        kind: 'story',
        targetId: 'story-failed',
        title: 'Failed',
        purpose: '',
        referenceSong: '',
        brief: '',
        style: 'metal',
        lyrics: '[Verse]\nFailed',
        lyriaPrompt: '',
        instrumental: false,
        durationSeconds: 30,
        candidates: [{
          id: failedId,
          status: 'failed',
          name: '',
          source: '',
          prompt: 'metal',
          lyrics: '[Verse]\nFailed',
          provider: 'local',
          model: 'ace_step_v1_5_xl_sft_lm_4b',
          durationSeconds: 30,
          createdAt: '2026-09-05T00:00:00.000Z',
        }],
      }],
    },
  })
  const recovered = recoverPendingStorySongs({ [project.id]: project }, [{
    candidateId: failedId,
    filename: 'late.wav',
    source: '/api/v1/file/late.wav',
    projectId: project.id,
    cueId: 'cue-failed',
  }])
  assert.equal(recovered.changed, true)
  const candidate = recovered.projects[project.id].music.cues[0].candidates[0]
  assert.equal(candidate.id, failedId)
  assert.equal(candidate.status, 'ready')
  assert.equal(candidate.name, 'late.wav')
})

test('recovery ignores a sidecar from another project or workspace candidate', async () => {
  const { recoverPendingStorySongs } = await import('../src/features/stories/storySongRecovery.ts')
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const project = normalizeStoryProject({
    ...base,
    id: 'story-b',
    music: {
      ...base.music,
      cues: [{
        id: 'cue-b',
        kind: 'story',
        targetId: 'story-b',
        title: 'B',
        purpose: '',
        referenceSong: '',
        brief: '',
        style: 'metal',
        lyrics: '[Verse]\nB',
        lyriaPrompt: '',
        instrumental: false,
        durationSeconds: 30,
        candidates: [{
          id: 'song-b',
          status: 'pending',
          name: '',
          source: '',
          prompt: 'metal',
          lyrics: '[Verse]\nB',
          provider: 'local',
          model: 'ace_step_v1_5_xl_sft_lm_4b',
          durationSeconds: 30,
          createdAt: '2026-09-05T00:00:00.000Z',
        }],
      }],
    },
  })
  const recovered = recoverPendingStorySongs({ [project.id]: project }, [{
    candidateId: 'song-a',
    filename: 'a.wav',
    source: '/api/v1/file/a.wav',
    projectId: 'story-a',
    cueId: 'cue-a',
  }])
  assert.equal(recovered.changed, false)
  assert.equal(recovered.projects[project.id].music.cues[0].candidates[0].status, 'pending')
})

test('loadWorkspace attaches a matching WAV after client close with no live generate promise', { concurrency: false }, async t => {
  const workspace = 'song-recover-hydrate'
  const { createStoryProject, normalizeStoryProject, useStoryStore } = await import('../src/features/stories/store.ts')
  const base = createStoryProject('music_video')
  const pendingId = 'song-closed-client'
  const project = normalizeStoryProject({
    ...base,
    id: 'story-closed',
    title: 'Closed client',
    music: {
      ...base.music,
      cues: [{
        id: 'cue-closed',
        kind: 'story',
        targetId: 'story-closed',
        title: 'Closed',
        purpose: '',
        referenceSong: '',
        brief: '',
        style: 'metal',
        lyrics: '[Verse]\nClosed',
        lyriaPrompt: '',
        instrumental: false,
        durationSeconds: 30,
        candidates: [{
          id: pendingId,
          status: 'pending',
          name: '',
          source: '',
          prompt: 'metal',
          lyrics: '[Verse]\nClosed',
          provider: 'local',
          model: 'ace_step_v1_5_xl_sft_lm_4b',
          durationSeconds: 30,
          createdAt: '2026-09-05T00:00:00.000Z',
        }],
        selectedCandidateId: pendingId,
      }],
    },
  })
  const library = {
    version: 2,
    revision: 4,
    activeId: project.id,
    projects: { [project.id]: project },
  }
  window.localStorage.setItem(`maestro-story-library-v2:${workspace}`, JSON.stringify(library))
  useStoryStore.setState({
    workspace: 'other',
    hydrated: false,
    loading: false,
    libraryConflicts: [],
  })
  const originalFetch = globalThis.fetch
  const putBodies = []
  t.after(() => {
    globalThis.fetch = originalFetch
    window.localStorage.removeItem(`maestro-story-library-v2:${workspace}`)
  })
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input)
    if (url.includes('/api/v1/stories/library?')) {
      return new Response(JSON.stringify(library), { headers: { 'content-type': 'application/json' } })
    }
    if (url.endsWith('/api/v1/stories/library') && init.method === 'PUT') {
      putBodies.push(JSON.parse(String(init.body)))
      const saved = {
        ...JSON.parse(String(init.body)).library,
        revision: 5,
      }
      return new Response(JSON.stringify(saved), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/assets')) {
      return new Response(JSON.stringify({
        assets: [{
          id: 'asset-closed',
          kind: 'audio',
          filename: 'closed.wav',
          size_bytes: 12,
          created_at: 1,
          completed_at: 1,
          metadata_status: 'canonical',
          workspace_ids: [workspace],
          locations: [{ workspace_id: workspace, filename: 'closed.wav', url: '/api/v1/file/closed.wav' }],
          url: '/api/v1/file/closed.wav?workspace=song-recover-hydrate',
          origin: {
            tool: 'story_lab',
            output_folder: workspace,
            project: { kind: 'story', id: project.id },
          },
          execution: { candidate_id: pendingId, cue_id: 'cue-closed', status: 'completed', mode: 'real' },
          model: { provider: 'local', id: 'ace_step_v1_5_xl_sft_lm_4b' },
          prompt_preview: 'metal',
        }],
        total: 1,
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/outputs')) {
      return new Response(JSON.stringify({ outputs: [], total: 0 }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  }

  await useStoryStore.getState().loadWorkspace(workspace)
  const recovered = useStoryStore.getState().projects[project.id].music.cues[0].candidates[0]
  assert.equal(recovered.id, pendingId)
  assert.equal(recovered.status, 'ready')
  assert.equal(recovered.name, 'closed.wav')
  assert.match(recovered.source, /closed\.wav/)
  assert.equal(putBodies.length, 1)
  assert.equal(putBodies[0].baseRevision, 4)
  assert.equal(
    putBodies[0].library.projects[project.id].music.cues[0].candidates[0].status,
    'ready',
  )
  assert.equal(useStoryStore.getState().libraryRevision, 5)
  assert.equal(useStoryStore.getState().dirty, false)
})

function pendingProject(overrides = {}) {
  return {
    id: 'song-job',
    status: 'pending',
    name: '',
    source: '',
    prompt: 'folk',
    lyrics: '[Verse]\nLa noche',
    provider: 'minimax',
    model: 'music-3.0',
    durationSeconds: 30,
    createdAt: '2026-09-05T00:00:00.000Z',
    provenance: { jobId: 'minimax-music-abc', outputFolder: 'lab', projectId: 'story-job', cueId: 'cue-job' },
    ...overrides,
  }
}

test('in-flight completed job rehydrates the reserved candidate by job id', async () => {
  const { recoverInFlightStorySongs } = await import('../src/features/stories/storySongJobRecovery.ts')
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const project = normalizeStoryProject({
    ...base,
    id: 'story-job',
    music: {
      ...base.music,
      cues: [{
        id: 'cue-job',
        kind: 'story',
        targetId: 'story-job',
        title: 'Job',
        purpose: '',
        referenceSong: '',
        brief: '',
        style: 'folk',
        lyrics: '[Verse]\nLa noche',
        lyriaPrompt: '',
        instrumental: false,
        durationSeconds: 30,
        candidates: [pendingProject()],
      }],
    },
  })
  const recovered = recoverInFlightStorySongs({ [project.id]: project }, [{
    jobId: 'minimax-music-abc',
    taskId: 'task-1',
    rootTaskId: 'task-1',
    workspace: 'lab',
    status: 'completed',
    phase: 'completed',
    message: 'done',
    current: 1,
    total: 1,
    progress: 100,
    provider: 'minimax',
    model: 'music-3.0',
    candidateId: 'song-job',
    candidates: [{
      filename: 'job.mp3',
      audio_path: '/tmp/job.mp3',
      source: '/api/v1/file/job.mp3',
      duration_seconds: 61.5,
      provider: 'minimax',
      model: 'music-3.0',
      taskId: 'task-1',
    }],
  }], { workspace: 'lab' })
  const candidate = recovered.projects[project.id].music.cues[0].candidates[0]
  assert.equal(recovered.changed, true)
  assert.equal(candidate.status, 'ready')
  assert.equal(candidate.name, 'job.mp3')
  assert.equal(candidate.durationSeconds, 61.5)
  assert.equal(candidate.provenance.jobId, 'minimax-music-abc')
})

test('in-flight job for another workspace does not write the current project', async () => {
  const { recoverInFlightStorySongs } = await import('../src/features/stories/storySongJobRecovery.ts')
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const project = normalizeStoryProject({
    ...base,
    id: 'story-job',
    music: {
      ...base.music,
      cues: [{
        id: 'cue-job',
        kind: 'story',
        targetId: 'story-job',
        title: 'Job',
        purpose: '',
        referenceSong: '',
        brief: '',
        style: 'folk',
        lyrics: '[Verse]\nLa noche',
        lyriaPrompt: '',
        instrumental: false,
        durationSeconds: 30,
        candidates: [pendingProject()],
      }],
    },
  })
  const recovered = recoverInFlightStorySongs({ [project.id]: project }, [{
    jobId: 'minimax-music-abc',
    taskId: 'task-1',
    rootTaskId: 'task-1',
    workspace: 'other-folder',
    status: 'completed',
    phase: 'completed',
    message: 'done',
    current: 1,
    total: 1,
    progress: 100,
    provider: 'minimax',
    model: 'music-3.0',
    candidates: [{
      filename: 'wrong.mp3',
      audio_path: '/tmp/wrong.mp3',
      source: '/api/v1/file/wrong.mp3',
      duration_seconds: 12,
      provider: 'minimax',
      model: 'music-3.0',
    }],
  }], { workspace: 'lab' })
  assert.equal(recovered.changed, false)
  assert.equal(recovered.projects[project.id].music.cues[0].candidates[0].status, 'pending')
})

test('a duplicated pending row does not inherit the reserved job audio', async () => {
  const { recoverInFlightStorySongs } = await import('../src/features/stories/storySongJobRecovery.ts')
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const project = normalizeStoryProject({
    ...base,
    id: 'story-job',
    music: {
      ...base.music,
      cues: [{
        id: 'cue-job',
        kind: 'story',
        targetId: 'story-job',
        title: 'Job',
        purpose: '',
        referenceSong: '',
        brief: '',
        style: 'folk',
        lyrics: '[Verse]\nLa noche',
        lyriaPrompt: '',
        instrumental: false,
        durationSeconds: 30,
        candidates: [
          pendingProject({ id: 'song-reserved' }),
          pendingProject({ id: 'song-copy', provenance: { jobId: 'minimax-music-abc', outputFolder: 'lab' } }),
        ],
      }],
    },
  })
  const recovered = recoverInFlightStorySongs({ [project.id]: project }, [{
    jobId: 'minimax-music-abc',
    taskId: 'task-1',
    rootTaskId: 'task-1',
    workspace: 'lab',
    status: 'completed',
    phase: 'completed',
    message: 'done',
    current: 1,
    total: 1,
    progress: 100,
    provider: 'minimax',
    model: 'music-3.0',
    candidateId: 'song-reserved',
    candidates: [{
      filename: 'job.mp3',
      audio_path: '/tmp/job.mp3',
      source: '/api/v1/file/job.mp3',
      duration_seconds: 61.5,
      provider: 'minimax',
      model: 'music-3.0',
    }],
  }], { workspace: 'lab' })
  const byId = Object.fromEntries(
    recovered.projects[project.id].music.cues[0].candidates.map(row => [row.id, row]),
  )
  assert.equal(byId['song-reserved'].status, 'ready')
  assert.equal(byId['song-reserved'].name, 'job.mp3')
  assert.equal(byId['song-copy'].status, 'pending')
  assert.equal(byId['song-copy'].source, '')
})

test('failed in-flight job without audio marks the reserved candidate failed', async () => {
  const { recoverInFlightStorySongs } = await import('../src/features/stories/storySongJobRecovery.ts')
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const project = normalizeStoryProject({
    ...base,
    id: 'story-job',
    music: {
      ...base.music,
      cues: [{
        id: 'cue-job',
        kind: 'story',
        targetId: 'story-job',
        title: 'Job',
        purpose: '',
        referenceSong: '',
        brief: '',
        style: 'folk',
        lyrics: '[Verse]\nLa noche',
        lyriaPrompt: '',
        instrumental: false,
        durationSeconds: 30,
        candidates: [pendingProject()],
      }],
    },
  })
  const recovered = recoverInFlightStorySongs({ [project.id]: project }, [{
    jobId: 'minimax-music-abc',
    taskId: 'task-1',
    rootTaskId: 'task-1',
    workspace: 'lab',
    status: 'failed',
    phase: 'failed',
    message: 'provider error',
    current: 0,
    total: 1,
    progress: 0,
    provider: 'minimax',
    model: 'music-3.0',
    candidateId: 'song-job',
    candidates: [],
  }], { workspace: 'lab' })
  assert.equal(recovered.projects[project.id].music.cues[0].candidates[0].status, 'failed')
})

test('a completed job without candidateId does not attach audio by walk order', async () => {
  const { recoverInFlightStorySongs } = await import('../src/features/stories/storySongJobRecovery.ts')
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const project = normalizeStoryProject({
    ...base,
    id: 'story-job',
    music: {
      ...base.music,
      cues: [{
        id: 'cue-job',
        kind: 'story',
        targetId: 'story-job',
        title: 'Job',
        purpose: '',
        referenceSong: '',
        brief: '',
        style: 'folk',
        lyrics: '[Verse]\nLa noche',
        lyriaPrompt: '',
        instrumental: false,
        durationSeconds: 30,
        candidates: [pendingProject({ id: 'song-copy' })],
      }],
    },
  })
  const recovered = recoverInFlightStorySongs({ [project.id]: project }, [{
    jobId: 'minimax-music-abc',
    taskId: 'task-1',
    rootTaskId: 'task-1',
    workspace: 'lab',
    status: 'completed',
    phase: 'completed',
    message: 'done',
    current: 1,
    total: 1,
    progress: 100,
    provider: 'minimax',
    model: 'music-3.0',
    candidates: [{
      filename: 'job.mp3',
      audio_path: '/tmp/job.mp3',
      source: '/api/v1/file/job.mp3',
      duration_seconds: 61.5,
      provider: 'minimax',
      model: 'music-3.0',
    }],
  }], { workspace: 'lab' })
  assert.equal(recovered.changed, false)
  assert.equal(recovered.projects[project.id].music.cues[0].candidates[0].status, 'pending')
})
