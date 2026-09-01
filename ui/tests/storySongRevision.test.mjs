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

test('song generation rebases its candidate when Story autosave wins the CAS race', { concurrency: false }, async t => {
  const workspace = 'wizard-song-cas-retry'
  const [{ useStore }, { useStoryStore, createStoryProject, normalizeStoryProject }] = await Promise.all([
    import('../src/stores/useStore.ts'),
    import('../src/features/stories/store.ts'),
  ])
  const base = createStoryProject('music_video')
  const cue = {
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
  const project = normalizeStoryProject({
    ...base,
    title: 'Videoclip CAS',
    music: {
      ...base.music,
      model: 'ace_step_v1_5_xl_sft_lm_4b',
      cues: [cue],
    },
  })
  const remoteLibrary = {
    version: 2,
    revision: 2,
    activeId: project.id,
    projects: { [project.id]: project },
  }
  let savedLibrary = remoteLibrary
  const putRevisions = []
  const originalFetch = globalThis.fetch
  t.after(() => {
    globalThis.fetch = originalFetch
    window.localStorage.removeItem(`maestro-story-library-v2:${workspace}`)
  })
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input)
    if (url.endsWith('/api/v1/director/generate-music')) {
      return new Response(JSON.stringify({
        audio_path: '/tmp/himno.wav',
        filename: 'himno.wav',
        style: cue.style,
        lyrics: cue.lyrics,
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/stories/library?')) {
      return new Response(JSON.stringify(savedLibrary), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/outputs?')) {
      return new Response(JSON.stringify({ outputs: [], total: 0 }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.endsWith('/api/v1/stories/library') && init.method === 'PUT') {
      const body = JSON.parse(String(init.body))
      putRevisions.push(body.baseRevision)
      if (putRevisions.length === 1) {
        return new Response(JSON.stringify({ detail: {
          code: 'story_library_revision_conflict',
          message: 'expected 1, current 2',
          expectedRevision: 1,
          currentRevision: 2,
        } }), { status: 409, headers: { 'content-type': 'application/json' } })
      }
      savedLibrary = { ...body.library, revision: 3 }
      return new Response(JSON.stringify(savedLibrary), { headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  }

  useStore.setState({ activeWorkspace: workspace })
  useStoryStore.setState({
    workspace,
    project,
    projects: { [project.id]: project },
    libraryRevision: 1,
    dirty: false,
    hydrated: true,
    loading: false,
    saveError: null,
    libraryConflicts: [],
    activeProjectOperations: {},
  })

  const { generateStorySong } = await import('../src/features/agent/labActions.ts')
  const result = await generateStorySong({
    type: 'generate_story_song',
    targetStoryTitle: project.title,
    cueTitle: cue.title,
    confirm: true,
  })

  assert.deepEqual(putRevisions, [1, 2])
  const meta = result.artifacts[0].metadata
  assert.equal(meta.cueTitle, cue.title)
  assert.equal(meta.outputName, 'himno.wav')
  const savedCue = savedLibrary.projects[project.id].music.cues[0]
  assert.equal(savedCue.selectedCandidateId, meta.candidateId)
  assert.equal(savedCue.candidates.length, 1)
  assert.equal(savedCue.candidates[0].id, meta.candidateId)
})
