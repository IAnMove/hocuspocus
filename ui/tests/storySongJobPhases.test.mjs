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

function cueFixture(base, extra = {}) {
  return {
    id: 'cue-phases',
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
    ...extra,
  }
}

function completedJob(workspace, extra = {}) {
  return {
    jobId: 'job-phases-1',
    taskId: 'task-phases-1',
    rootTaskId: 'task-phases-1',
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
    ...extra,
  }
}

async function installStory(workspace, project, revision = 1, extraProjects = {}) {
  const { useStore } = await import('../src/stores/useStore.ts')
  const { useStoryStore } = await import('../src/features/stories/store.ts')
  useStore.setState({ activeWorkspace: workspace })
  useStoryStore.setState({
    workspace,
    project,
    projects: { [project.id]: project, ...extraProjects },
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
  const putBodies = []
  const events = []
  let generationRequest
  let jobPolls = 0
  const originalFetch = globalThis.fetch
  t.after(() => {
    globalThis.fetch = originalFetch
    window.localStorage.removeItem(`maestro-story-library-v2:${workspace}`)
  })
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input)
    const method = String(init.method || 'GET').toUpperCase()
    if (url.endsWith('/api/v1/stories/music-candidates/jobs') && method === 'POST') {
      events.push('post-job')
      generationRequest = JSON.parse(String(init.body || '{}'))
      if (typeof options.onPostJob === 'function') options.onPostJob()
      const body = options.postJob || completedJob(workspace, {
        candidateId: generationRequest.provenance?.candidate_id,
      })
      return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/stories/music-candidates/jobs/') && method === 'GET') {
      events.push('get-job')
      jobPolls += 1
      const body = typeof options.pollJob === 'function'
        ? options.pollJob(jobPolls)
        : (options.pollJob || completedJob(workspace))
      return new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
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
    if (url.endsWith('/api/v1/stories/library') && method === 'PUT') {
      const body = JSON.parse(String(init.body))
      const pendingJob = Object.values(body.library?.projects || {}).flatMap(project => (
        (project.music?.cues || []).flatMap(cue => cue.candidates || [])
      )).find(item => item.status === 'pending' && item.provenance?.jobId)
      if (options.failJobPersist && pendingJob) {
        events.push('put-fail')
        return new Response(JSON.stringify({ detail: 'library persist failed' }), {
          status: 500, headers: { 'content-type': 'application/json' },
        })
      }
      putBodies.push(body.library)
      events.push('put')
      savedLibrary.value = { ...body.library, revision: body.baseRevision + 1 }
      return new Response(JSON.stringify(savedLibrary.value), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url} ${method}`)
  }
  return { putBodies, events, get generationRequest() { return generationRequest } }
}

test('story song idempotency keys stay bound to the reserved candidate', async () => {
  const { storySongIdempotencyKey } = await import('../src/features/stories/storySongGeneration.ts')
  assert.equal(
    storySongIdempotencyKey('ws', 'story-1', 'cue-1', 'song-9'),
    'story-song:ws:story-1:cue-1:song-9',
  )
  assert.notEqual(
    storySongIdempotencyKey('ws', 'story-1', 'cue-1', 'song-9'),
    storySongIdempotencyKey('ws', 'story-1', 'cue-1', 'song-10'),
  )
})

test('musicJobExecutionPhase maps durable MiniMax statuses', async () => {
  const { musicJobExecutionPhase } = await import('../src/features/stories/storySongJobPhases.ts')
  assert.equal(musicJobExecutionPhase({ status: 'queued', phase: 'queued' }), 'accepted')
  assert.equal(musicJobExecutionPhase({ status: 'waiting_resource', phase: 'waiting_resource' }), 'waiting_resource')
  assert.equal(musicJobExecutionPhase({ status: 'running', phase: 'running' }), 'executing')
  assert.equal(musicJobExecutionPhase({ status: 'cancelling', phase: 'cancelling' }), 'cancelling')
  assert.equal(musicJobExecutionPhase({ status: 'completed', phase: 'completed' }), 'terminal')
  assert.equal(musicJobExecutionPhase({ status: 'failed', phase: 'failed' }), 'terminal')
})

test('upsertCueMusicCandidate keeps the user-selected song', async () => {
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const { upsertCueMusicCandidate } = await import('../src/features/stories/musicWorkflowState.ts')
  const base = createStoryProject('music_video')
  const ready = {
    id: 'song-keep',
    name: 'keep.wav',
    source: '/api/v1/file/keep.wav',
    prompt: 'folk',
    lyrics: '[Verse]\nKeep',
    provider: 'minimax',
    model: 'music-3.0',
    durationSeconds: 30,
    createdAt: '2026-09-05T00:00:00.000Z',
    status: 'ready',
  }
  const pending = {
    id: 'song-new',
    name: '',
    source: '',
    prompt: 'folk',
    lyrics: '[Verse]\nKeep',
    provider: 'minimax',
    model: 'music-3.0',
    durationSeconds: 30,
    createdAt: '2026-09-05T00:00:01.000Z',
    status: 'pending',
    executionPhase: 'prepared',
  }
  const project = normalizeStoryProject({
    ...base,
    music: {
      ...base.music,
      selectedCandidateId: 'song-global',
      candidates: [{ ...ready, id: 'song-global' }],
      cues: [{
        ...cueFixture(base),
        candidates: [ready],
        selectedCandidateId: 'song-keep',
      }],
    },
  })
  const next = upsertCueMusicCandidate(project, project.music.cues[0].id, pending)
  assert.equal(next.music.cues[0].selectedCandidateId, 'song-keep')
  assert.equal(next.music.selectedCandidateId, 'song-global')
  assert.equal(next.music.cues[0].candidates.length, 2)
})

test('overlaySavedCueCandidates keeps a server-only sibling cue', async () => {
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const { overlaySavedCueCandidates } = await import('../src/features/stories/musicWorkflowState.ts')
  const base = createStoryProject('music_video')
  const opening = cueFixture(base, { id: 'cue-opening', title: 'Opening' })
  const creditsSong = {
    id: 'song-credits',
    name: 'credits.wav',
    source: '/api/v1/file/credits.wav',
    prompt: 'credits',
    lyrics: '[Verse]\nFin',
    provider: 'local',
    model: 'ace_step_v1_5_xl_sft_lm_4b',
    durationSeconds: 20,
    createdAt: '2026-09-21T00:00:00.000Z',
    status: 'ready',
  }
  const live = normalizeStoryProject({
    ...base,
    music: { ...base.music, cues: [opening] },
  })
  const pending = {
    id: 'song-opening',
    name: '',
    source: '',
    prompt: opening.style,
    lyrics: opening.lyrics,
    provider: 'local',
    model: 'ace_step_v1_5_xl_sft_lm_4b',
    durationSeconds: 30,
    createdAt: '2026-09-21T00:00:01.000Z',
    status: 'pending',
  }
  const saved = normalizeStoryProject({
    ...live,
    music: {
      ...live.music,
      cues: [
        { ...opening, candidates: [pending], selectedCandidateId: pending.id },
        {
          ...cueFixture(base, { id: 'cue-credits', title: 'Créditos', targetId: `${base.id}-credits` }),
          candidates: [creditsSong],
          selectedCandidateId: creditsSong.id,
        },
      ],
    },
  })
  const merged = overlaySavedCueCandidates(live, saved)
  const ids = merged.music.cues.map(cue => cue.id)
  assert.deepEqual(ids, ['cue-opening', 'cue-credits'])
  assert.equal(merged.music.cues[0].candidates[0].id, pending.id)
  assert.equal(merged.music.cues[1].candidates[0].id, creditsSong.id)
  assert.equal(merged.music.cues[1].candidates[0].source, creditsSong.source)
})

test('reusableInFlightSongCandidate prefers a pending row with jobId', async () => {
  const { reusableInFlightSongCandidate } = await import('../src/features/stories/storySongJobPhases.ts')
  const first = {
    id: 'song-a', status: 'pending', name: '', source: '', prompt: 'a', lyrics: '', provider: 'minimax',
    model: 'music-3.0', durationSeconds: 30, createdAt: '2026-09-05T00:00:00.000Z',
  }
  const withJob = {
    ...first,
    id: 'song-b',
    provenance: { jobId: 'job-keep' },
  }
  assert.equal(reusableInFlightSongCandidate([first, withJob])?.id, 'song-b')
  assert.equal(reusableInFlightSongCandidate([first])?.id, 'song-a')
  assert.equal(reusableInFlightSongCandidate([{ ...first, status: 'ready', source: '/x' }]), undefined)
})

test('remote generate persists the 202 job id before audio is ready', { concurrency: false }, async t => {
  const workspace = 'story-job-202'
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const cue = cueFixture(base)
  const project = normalizeStoryProject({
    ...base,
    title: 'Job phases',
    music: { ...base.music, model: 'music-3.0', cues: [cue] },
  })
  const savedLibrary = {
    value: { version: 2, revision: 1, activeId: project.id, projects: { [project.id]: project } },
  }
  const mock = mockStoryFetch(t, workspace, savedLibrary, {
    postJob: completedJob(workspace, {
      status: 'queued',
      phase: 'queued',
      message: 'Music generation accepted',
      current: 0,
      progress: 0,
      candidates: [],
    }),
    pollJob: completedJob(workspace),
  })
  await installStory(workspace, project, 1)
  const { generateStoryCueSong } = await import('../src/features/stories/storySongGeneration.ts')
  const generated = await generateStoryCueSong({
    workspace,
    projectId: project.id,
    cueId: cue.id,
    actor: 'user',
    capability: 'generate_story_song',
  })
  assert.ok(mock.events.indexOf('put') < mock.events.indexOf('post-job'))
  const accepted = mock.putBodies.find(library => {
    const row = library.projects[project.id].music.cues[0].candidates[0]
    return row?.provenance?.jobId === 'job-phases-1' && row.status === 'pending'
  })
  assert.ok(accepted)
  const acceptedRow = accepted.projects[project.id].music.cues[0].candidates[0]
  assert.equal(acceptedRow.executionPhase, 'accepted')
  assert.equal(acceptedRow.id, generated.candidateId)
  const ready = savedLibrary.value.projects[project.id].music.cues[0].candidates[0]
  assert.equal(ready.status, 'ready')
  assert.equal(ready.executionPhase, 'terminal')
  assert.equal(ready.provenance.jobId, 'job-phases-1')
})

test('double generate on the same cue shares one candidate and one POST', { concurrency: false }, async t => {
  const workspace = 'story-job-double'
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const cue = cueFixture(base)
  const project = normalizeStoryProject({
    ...base,
    title: 'Double tab',
    music: { ...base.music, model: 'music-3.0', cues: [cue] },
  })
  const savedLibrary = {
    value: { version: 2, revision: 1, activeId: project.id, projects: { [project.id]: project } },
  }
  const mock = mockStoryFetch(t, workspace, savedLibrary)
  await installStory(workspace, project, 1)
  const { generateStoryCueSong } = await import('../src/features/stories/storySongGeneration.ts')
  const input = {
    workspace,
    projectId: project.id,
    cueId: cue.id,
    actor: 'user',
    capability: 'generate_story_song',
  }
  const [first, second] = await Promise.all([
    generateStoryCueSong(input),
    generateStoryCueSong(input),
  ])
  assert.equal(first.candidateId, second.candidateId)
  assert.equal(mock.events.filter(event => event === 'post-job').length, 1)
  assert.equal(savedLibrary.value.projects[project.id].music.cues[0].candidates.length, 1)
})

test('late job persist keeps the user-selected song and the other open Story', { concurrency: false }, async t => {
  const workspace = 'story-job-context'
  const { createStoryProject, normalizeStoryProject, useStoryStore } = await import('../src/features/stories/store.ts')
  const base = createStoryProject('music_video')
  const otherBase = createStoryProject('music_video')
  const ready = {
    id: 'song-keep',
    name: 'keep.wav',
    source: '/api/v1/file/keep.wav',
    prompt: 'folk',
    lyrics: '[Verse]\nKeep',
    provider: 'minimax',
    model: 'music-3.0',
    durationSeconds: 30,
    createdAt: '2026-09-05T00:00:00.000Z',
    status: 'ready',
  }
  const cue = cueFixture(base, { candidates: [ready], selectedCandidateId: 'song-keep' })
  const project = normalizeStoryProject({
    ...base,
    title: 'Generating',
    music: { ...base.music, model: 'music-3.0', cues: [cue] },
  })
  const other = normalizeStoryProject({
    ...otherBase,
    title: 'Other story',
  })
  const savedLibrary = {
    value: {
      version: 2,
      revision: 1,
      activeId: project.id,
      projects: { [project.id]: project, [other.id]: other },
    },
  }
  const mock = mockStoryFetch(t, workspace, savedLibrary, {
    onPostJob: () => {
      useStoryStore.setState({ project: useStoryStore.getState().projects[other.id] })
    },
  })
  await installStory(workspace, project, 1, { [other.id]: other })
  const { generateStoryCueSong } = await import('../src/features/stories/storySongGeneration.ts')
  const generated = await generateStoryCueSong({
    workspace,
    projectId: project.id,
    cueId: cue.id,
    actor: 'user',
    capability: 'generate_story_song',
  })
  const savedCue = savedLibrary.value.projects[project.id].music.cues[0]
  assert.equal(savedCue.selectedCandidateId, 'song-keep')
  assert.equal(savedCue.candidates.some(item => item.id === generated.candidateId), true)
  assert.equal(savedLibrary.value.activeId, other.id)
  assert.equal(useStoryStore.getState().project.id, other.id)
  const jobPuts = mock.putBodies.filter(library => (
    library.projects[project.id].music.cues[0].candidates.some(item => item.provenance?.jobId)
  ))
  assert.ok(jobPuts.every(library => library.activeId === other.id))
})

test('reload reconnects a reserved pending job without posting a new one', { concurrency: false }, async t => {
  const workspace = 'story-job-reconnect'
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const pending = {
    id: 'song-reserved',
    name: '',
    source: '',
    prompt: 'Heavy metal ochentero con voz ronca y coro grave.',
    lyrics: '[Verse]\nLa red sigue viva.\n[Chorus]\nReinicia.',
    provider: 'minimax',
    model: 'music-3.0',
    durationSeconds: 30,
    createdAt: '2026-09-05T00:00:00.000Z',
    status: 'pending',
    executionPhase: 'accepted',
    provenance: { jobId: 'job-phases-1', projectId: base.id, cueId: 'cue-phases' },
  }
  const cue = cueFixture(base, { candidates: [pending] })
  const project = normalizeStoryProject({
    ...base,
    title: 'Reconnect',
    music: { ...base.music, model: 'music-3.0', cues: [cue] },
  })
  const savedLibrary = {
    value: { version: 2, revision: 1, activeId: project.id, projects: { [project.id]: project } },
  }
  const mock = mockStoryFetch(t, workspace, savedLibrary, {
    pollJob: completedJob(workspace, { candidateId: 'song-reserved' }),
  })
  await installStory(workspace, project, 1)
  const { generateStoryCueSong } = await import('../src/features/stories/storySongGeneration.ts')
  const generated = await generateStoryCueSong({
    workspace,
    projectId: project.id,
    cueId: project.music.cues[0].id,
    actor: 'user',
    capability: 'generate_story_song',
  })
  assert.equal(generated.candidateId, 'song-reserved')
  assert.equal(mock.events.filter(event => event === 'post-job').length, 0)
  assert.ok(mock.events.includes('get-job'))
  assert.equal(savedLibrary.value.projects[project.id].music.cues[0].candidates[0].status, 'ready')
})

test('MusicCueCard shows execution phases and hides audio until a source exists', () => {
  const source = readFileSync(new URL('../src/features/stories/MusicCueCard.tsx', import.meta.url), 'utf8')
  assert.match(source, /CueCandidateRow/)
  assert.match(source, /music\.executionPhase/)
  assert.match(source, /music\.candidateFailed/)
  assert.match(source, /const playable = Boolean\(candidate\.source\.trim\(\)\)/)
  assert.match(source, /\{playable \? \(\s*<audio/)
})

test('a failed job persist still watches the accepted MiniMax job', { concurrency: false }, async t => {
  const workspace = 'story-job-persist-fail'
  const { createStoryProject, normalizeStoryProject } = await import('../src/features/stories/model.ts')
  const base = createStoryProject('music_video')
  const cue = cueFixture(base)
  const project = normalizeStoryProject({
    ...base,
    title: 'Persist fail',
    music: { ...base.music, model: 'music-3.0', cues: [cue] },
  })
  const savedLibrary = {
    value: { version: 2, revision: 1, activeId: project.id, projects: { [project.id]: project } },
  }
  const mock = mockStoryFetch(t, workspace, savedLibrary, {
    failJobPersist: true,
    postJob: completedJob(workspace, {
      status: 'queued',
      phase: 'queued',
      message: 'Music generation accepted',
      current: 0,
      progress: 0,
      candidates: [],
    }),
    pollJob: completedJob(workspace),
  })
  await installStory(workspace, project, 1)
  const { generateStoryCueSong } = await import('../src/features/stories/storySongGeneration.ts')
  const generated = await generateStoryCueSong({
    workspace,
    projectId: project.id,
    cueId: cue.id,
    actor: 'user',
    capability: 'generate_story_song',
  })
  assert.ok(mock.events.includes('put-fail'))
  assert.ok(mock.events.includes('get-job'))
  assert.equal(
    mock.generationRequest.idempotency_key,
    `story-song:${workspace}:${project.id}:${cue.id}:${generated.candidateId}`,
  )
  assert.equal(generated.candidate.status, 'ready')
  assert.equal(savedLibrary.value.projects[project.id].music.cues[0].candidates[0].status, 'ready')
})

test('phase persist does not restore other Stories from the persist snapshot', { concurrency: false }, async t => {
  const workspace = 'story-job-live-library'
  const { createStoryProject, normalizeStoryProject, useStoryStore } = await import('../src/features/stories/store.ts')
  const base = createStoryProject('music_video')
  const otherBase = createStoryProject('music_video')
  const cue = cueFixture(base)
  const project = normalizeStoryProject({
    ...base,
    title: 'Generating',
    music: { ...base.music, model: 'music-3.0', cues: [cue] },
  })
  const other = normalizeStoryProject({
    ...otherBase,
    title: 'Sibling story',
  })
  const savedLibrary = {
    value: {
      version: 2,
      revision: 1,
      activeId: project.id,
      projects: { [project.id]: project, [other.id]: other },
    },
  }
  mockStoryFetch(t, workspace, savedLibrary, {
    onPostJob: () => {
      const current = useStoryStore.getState()
      const liveOther = { ...current.projects[other.id], title: 'Edited sibling' }
      useStoryStore.setState({
        projects: { ...current.projects, [other.id]: liveOther },
        dirty: true,
      })
    },
  })
  await installStory(workspace, project, 1, { [other.id]: other })
  const { generateStoryCueSong } = await import('../src/features/stories/storySongGeneration.ts')
  await generateStoryCueSong({
    workspace,
    projectId: project.id,
    cueId: cue.id,
    actor: 'user',
    capability: 'generate_story_song',
  })
  assert.equal(useStoryStore.getState().projects[other.id].title, 'Edited sibling')
  assert.equal(useStoryStore.getState().dirty, true)
})

test('phase persist keeps cue edits typed while the job is running', { concurrency: false }, async t => {
  const workspace = 'story-job-keep-edits'
  const { createStoryProject, normalizeStoryProject, useStoryStore } = await import('../src/features/stories/store.ts')
  const base = createStoryProject('music_video')
  const cue = cueFixture(base)
  const project = normalizeStoryProject({
    ...base,
    title: 'Keep edits',
    music: { ...base.music, model: 'music-3.0', cues: [cue] },
  })
  const savedLibrary = {
    value: { version: 2, revision: 1, activeId: project.id, projects: { [project.id]: project } },
  }
  mockStoryFetch(t, workspace, savedLibrary, {
    onPostJob: () => {
      const current = useStoryStore.getState()
      const live = current.projects[project.id]
      const next = {
        ...live,
        music: {
          ...live.music,
          cues: live.music.cues.map(item => item.id === cue.id
            ? { ...item, purpose: 'Edited while generating' }
            : item),
        },
      }
      useStoryStore.setState({
        project: next,
        projects: { ...current.projects, [project.id]: next },
        dirty: true,
      })
    },
  })
  await installStory(workspace, project, 1)
  const { generateStoryCueSong } = await import('../src/features/stories/storySongGeneration.ts')
  await generateStoryCueSong({
    workspace,
    projectId: project.id,
    cueId: cue.id,
    actor: 'user',
    capability: 'generate_story_song',
  })
  const kept = useStoryStore.getState().projects[project.id].music.cues[0]
  assert.equal(kept.purpose, 'Edited while generating')
  assert.equal(useStoryStore.getState().dirty, true)
})
