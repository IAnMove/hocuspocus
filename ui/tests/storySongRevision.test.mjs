import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
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

function cueFixture(base) {
  return {
    id: 'cue-canonical',
    kind: 'story',
    targetId: base.id,
    title: 'Himno visible',
    purpose: 'Himno del sysadmin',
    referenceSong: '',
    brief: 'Metal español',
    style: 'Heavy metal ochentero con voz ronca y coro grave.',
    lyrics: '[Verse]\nLa red sigue viva.\n[Chorus]\nReinicia.',
    lyricsLanguage: 'Español',
    lyriaPrompt: '',
    instrumental: false,
    durationSeconds: 30,
    candidates: [],
  }
}

async function installStory(workspace, project, revision = 1) {
  const { useStore } = await import('../src/stores/useStore.ts')
  const { useStoryStore } = await import('../src/features/stories/store.ts')
  useStore.setState({ activeWorkspace: workspace })
  useStoryStore.setState({
    workspace,
    project,
    projects: { [project.id]: project },
    libraryRevision: revision,
    dirty: false,
    hydrated: true,
    loading: false,
    saveError: null,
    libraryConflicts: [],
    activeProjectOperations: {},
  })
}

function mockStoryFetch(t, workspace, savedLibrary, options = {}) {
  const putRevisions = []
  const events = []
  const putBodies = []
  let generationRequest
  const originalFetch = globalThis.fetch
  t.after(() => {
    globalThis.fetch = originalFetch
    window.localStorage.removeItem(`maestro-story-library-v2:${workspace}`)
  })
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input)
    if (url.endsWith('/api/v1/director/generate-music')) {
      events.push('generate')
      if (options.failGenerate) {
        return new Response(JSON.stringify({ detail: 'music failed' }), {
          status: 500, headers: { 'content-type': 'application/json' },
        })
      }
      generationRequest = JSON.parse(String(init.body || '{}'))
      return new Response(JSON.stringify({
        audio_path: '/tmp/himno.wav',
        filename: 'himno.wav',
        style: 'Heavy metal',
        lyrics: '[Verse]\nLa red sigue viva.',
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/stories/music-candidates/jobs')) {
      events.push('generate')
      generationRequest = JSON.parse(String(init.body || '{}'))
      return new Response(JSON.stringify({
        jobId: 'job-1',
        taskId: 'task-1',
        rootTaskId: 'task-1',
        workspace,
        status: 'completed',
        phase: 'completed',
        message: 'done',
        current: 1,
        total: 1,
        progress: 1,
        provider: 'minimax',
        model: 'music-3.0',
        candidates: [{
          filename: 'himno.wav',
          audio_path: '/tmp/himno.wav',
          source: '/api/v1/file/himno.wav',
          duration_seconds: 30,
          provider: 'minimax',
          model: 'music-3.0',
        }],
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/assets')) {
      return new Response(JSON.stringify({ assets: [], total: 0 }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.includes('/api/v1/outputs')) {
      return new Response(JSON.stringify({ outputs: [], total: 0 }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.includes('/api/v1/stories/library?')) {
      return new Response(JSON.stringify(savedLibrary.value), {
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.endsWith('/api/v1/stories/library') && init.method === 'PUT') {
      const body = JSON.parse(String(init.body))
      putRevisions.push(body.baseRevision)
      putBodies.push(body.library)
      events.push('put')
      if (options.conflictFirst && putRevisions.length === 1) {
        return new Response(JSON.stringify({ detail: {
          code: 'story_library_revision_conflict',
          message: 'expected 1, current 2',
          expectedRevision: 1,
          currentRevision: savedLibrary.value.revision,
        } }), { status: 409, headers: { 'content-type': 'application/json' } })
      }
      savedLibrary.value = { ...body.library, revision: body.baseRevision + 1 }
      return new Response(JSON.stringify(savedLibrary.value), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url}`)
  }
  return { putRevisions, putBodies, events, get generationRequest() { return generationRequest } }
}

test('song generation saves a pending candidate before generate-music HTTP', { concurrency: false }, async t => {
  const workspace = 'wizard-song-pending-first'
  const [{ createStoryProject, normalizeStoryProject }] = await Promise.all([
    import('../src/features/stories/store.ts'),
  ])
  const base = createStoryProject('music_video')
  const cue = cueFixture(base)
  const project = normalizeStoryProject({
    ...base,
    title: 'Videoclip pending',
    music: { ...base.music, model: 'ace_step_v1_5_xl_sft_lm_4b', cues: [cue] },
  })
  const savedLibrary = {
    value: { version: 2, revision: 1, activeId: project.id, projects: { [project.id]: project } },
  }
  const mock = mockStoryFetch(t, workspace, savedLibrary)
  await installStory(workspace, project, 1)

  const { generateStorySong } = await import('../src/features/agent/labActions.ts')
  const result = await generateStorySong({
    type: 'generate_story_song',
    targetStoryTitle: project.title,
    cueTitle: cue.title,
    confirm: true,
  })

  assert.equal(mock.events[0], 'put')
  assert.ok(mock.events.indexOf('put') < mock.events.indexOf('generate'))
  const pendingPut = mock.putBodies[0]
  const pendingCandidate = pendingPut.projects[project.id].music.cues[0].candidates[0]
  assert.equal(pendingCandidate.status, 'pending')
  assert.equal(pendingCandidate.source, '')
  assert.match(pendingCandidate.id, /^song-/)
  const meta = result.artifacts[0].metadata
  assert.equal(pendingCandidate.id, meta.candidateId)
  const ready = savedLibrary.value.projects[project.id].music.cues[0].candidates[0]
  assert.equal(ready.id, meta.candidateId)
  assert.equal(ready.status, 'ready')
  assert.equal(ready.name, 'himno.wav')
  assert.equal(mock.generationRequest.provenance.candidate_id, meta.candidateId)
  assert.equal(mock.generationRequest.provenance.song_version, String(meta.songVersion))
  assert.equal(mock.generationRequest.provenance.project_id, project.id)
  assert.equal(mock.generationRequest.provenance.cue_id, cue.id)
  assert.equal(mock.generationRequest.provenance.workspace_id, undefined)
})

test('song generation rebases its candidate when Story autosave wins the CAS race', { concurrency: false }, async t => {
  const workspace = 'wizard-song-cas-retry'
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/store.ts')
  const base = createStoryProject('music_video')
  const cue = cueFixture(base)
  const project = normalizeStoryProject({
    ...base,
    title: 'Videoclip CAS',
    music: { ...base.music, model: 'ace_step_v1_5_xl_sft_lm_4b', cues: [cue] },
  })
  const savedLibrary = {
    value: { version: 2, revision: 2, activeId: project.id, projects: { [project.id]: project } },
  }
  const mock = mockStoryFetch(t, workspace, savedLibrary, { conflictFirst: true })
  await installStory(workspace, project, 1)

  const { generateStorySong } = await import('../src/features/agent/labActions.ts')
  const result = await generateStorySong({
    type: 'generate_story_song',
    targetStoryTitle: project.title,
    cueTitle: cue.title,
    confirm: true,
  })

  assert.deepEqual(mock.putRevisions.slice(0, 2), [1, 2])
  const meta = result.artifacts[0].metadata
  const savedCue = savedLibrary.value.projects[project.id].music.cues[0]
  assert.equal(savedCue.selectedCandidateId, meta.candidateId)
  assert.equal(savedCue.candidates.length, 1)
  assert.equal(savedCue.candidates[0].id, meta.candidateId)
  assert.equal(mock.generationRequest.provenance.candidate_id, meta.candidateId)
  const pendingIds = mock.putBodies.map(body => body.projects[project.id].music.cues[0].candidates[0]?.id)
  assert.ok(pendingIds.every(id => id === meta.candidateId))
})

test('failed generation keeps the minted candidate id as failed', { concurrency: false }, async t => {
  const workspace = 'wizard-song-failed-id'
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/store.ts')
  const base = createStoryProject('music_video')
  const cue = cueFixture(base)
  const project = normalizeStoryProject({
    ...base,
    title: 'Videoclip fail',
    music: { ...base.music, model: 'ace_step_v1_5_xl_sft_lm_4b', cues: [cue] },
  })
  const savedLibrary = {
    value: { version: 2, revision: 1, activeId: project.id, projects: { [project.id]: project } },
  }
  mockStoryFetch(t, workspace, savedLibrary, { failGenerate: true })
  await installStory(workspace, project, 1)

  const { generateStorySong } = await import('../src/features/agent/labActions.ts')
  await assert.rejects(
    () => generateStorySong({
      type: 'generate_story_song',
      targetStoryTitle: project.title,
      cueTitle: cue.title,
      confirm: true,
    }),
    /music failed/,
  )
  const savedCue = savedLibrary.value.projects[project.id].music.cues[0]
  assert.equal(savedCue.candidates.length, 1)
  assert.match(savedCue.candidates[0].id, /^song-/)
  assert.equal(savedCue.candidates[0].status, 'failed')
  assert.equal(savedCue.candidates[0].source, '')
})

test('a missing cue id throws instead of picking another cue', { concurrency: false }, async t => {
  const workspace = 'wizard-song-missing-cue'
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/store.ts')
  const base = createStoryProject('music_video')
  const cue = cueFixture(base)
  const project = normalizeStoryProject({
    ...base,
    title: 'Videoclip cue',
    music: { ...base.music, model: 'ace_step_v1_5_xl_sft_lm_4b', cues: [cue] },
  })
  const savedLibrary = {
    value: { version: 2, revision: 1, activeId: project.id, projects: { [project.id]: project } },
  }
  mockStoryFetch(t, workspace, savedLibrary)
  await installStory(workspace, project, 1)
  const { generateStorySong } = await import('../src/features/agent/labActions.ts')
  await assert.rejects(
    () => generateStorySong({
      type: 'generate_story_song',
      targetStoryTitle: project.title,
      cueTitle: cue.title,
      cueId: 'cue-missing',
      confirm: true,
    }),
    /No existe el cue con ID/,
  )
})

test('Wizard generate uses the open project when title is omitted', { concurrency: false }, async t => {
  const workspace = 'wizard-song-open-project'
  const { createStoryProject, normalizeStoryProject, useStoryStore } = await import('../src/features/stories/store.ts')
  const otherBase = createStoryProject('music_video')
  const openBase = createStoryProject('music_video')
  const other = normalizeStoryProject({
    ...otherBase,
    title: 'Other story',
    music: { ...otherBase.music, model: 'ace_step_v1_5_xl_sft_lm_4b', cues: [cueFixture(otherBase)] },
  })
  const openCue = cueFixture(openBase)
  const open = normalizeStoryProject({
    ...openBase,
    title: 'Open story',
    music: { ...openBase.music, model: 'ace_step_v1_5_xl_sft_lm_4b', cues: [openCue] },
  })
  const savedLibrary = {
    value: {
      version: 2,
      revision: 1,
      activeId: open.id,
      projects: { [other.id]: other, [open.id]: open },
    },
  }
  const mock = mockStoryFetch(t, workspace, savedLibrary)
  await installStory(workspace, open, 1)
  useStoryStore.setState({
    project: open,
    projects: { [other.id]: other, [open.id]: open },
  })

  const { generateStorySong } = await import('../src/features/agent/labActions.ts')
  const result = await generateStorySong({
    type: 'generate_story_song',
    targetStoryTitle: '',
    cueTitle: '',
    confirm: true,
  })
  assert.equal(result.artifacts[0].metadata.projectId, open.id)
  assert.equal(mock.generationRequest.provenance.project_id, open.id)
  assert.equal(mock.generationRequest.provenance.cue_id, openCue.id)
})

test('generateStoryCueSong sends provenance with candidate_id for the Story Lab path', { concurrency: false }, async t => {
  const workspace = 'story-lab-cue-audio'
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/store.ts')
  const base = createStoryProject('music_video')
  const cue = cueFixture(base)
  const project = normalizeStoryProject({
    ...base,
    title: 'Story Lab song',
    music: { ...base.music, model: 'ace_step_v1_5_xl_sft_lm_4b', cues: [cue] },
  })
  const savedLibrary = {
    value: { version: 2, revision: 1, activeId: project.id, projects: { [project.id]: project } },
  }
  const mock = mockStoryFetch(t, workspace, savedLibrary)
  await installStory(workspace, project, 1)
  const { generateStoryCueSong } = await import('../src/features/stories/storySongGeneration.ts')
  const generated = await generateStoryCueSong({
    workspace,
    projectId: project.id,
    cueId: cue.id,
    actor: 'user',
    capability: 'generate_story_song',
  })
  assert.equal(mock.generationRequest.provenance.actor, 'user')
  assert.equal(mock.generationRequest.provenance.candidate_id, generated.candidateId)
  assert.equal(mock.generationRequest.provenance.cue_id, cue.id)
  assert.equal(mock.events[0], 'put')
  const panel = readFileSync(new URL('../src/features/stories/StoryLabPanel.tsx', import.meta.url), 'utf8')
  assert.match(panel, /generateStoryCueSong/)
  assert.match(panel, /generateMusicCueAudio/)
})
