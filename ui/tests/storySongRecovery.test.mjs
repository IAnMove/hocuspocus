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
  t.after(() => {
    globalThis.fetch = originalFetch
    window.localStorage.removeItem(`maestro-story-library-v2:${workspace}`)
  })
  globalThis.fetch = async input => {
    const url = String(input)
    if (url.includes('/api/v1/stories/library?')) {
      return new Response(JSON.stringify(library), { headers: { 'content-type': 'application/json' } })
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
})
