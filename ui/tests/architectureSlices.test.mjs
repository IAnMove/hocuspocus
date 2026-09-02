import assert from 'node:assert/strict'
import test from 'node:test'

const { prependJob, updateJob, removeJob, markJobsCancelling } = await import('../src/stores/jobReducers.ts')

function job(id, status = 'queued') {
  return {
    id,
    status,
    progress: 0,
    step: 0,
    totalSteps: 1,
    phase: '',
    message: '',
    outputFiles: [],
    error: null,
    oomInfo: null,
    createdAt: 1,
  }
}

test('job reducers preserve queue order and derive busy state from active jobs', () => {
  const first = job('first', 'failed')
  const active = job('active')
  const added = prependJob([first], active)
  assert.deepEqual(added.jobs.map(item => item.id), ['active', 'first'])
  assert.equal(added.isGenerating, true)

  const terminal = updateJob(added.jobs, item => item.id === 'active', item => ({ ...item, status: 'completed' }))
  assert.equal(terminal.isGenerating, false)
  assert.deepEqual(terminal.jobs.map(item => item.status), ['completed', 'failed'])

  const removed = removeJob(terminal.jobs, item => item.id === 'active')
  assert.deepEqual(removed.jobs.map(item => item.id), ['first'])
  assert.equal(removed.isGenerating, false)
})

test('cancelling reducer changes only active target jobs and keeps their tiles', () => {
  const jobs = [job('running', 'running'), job('failed', 'failed'), job('queued', 'queued')]
  const result = markJobsCancelling(jobs, new Set(['running', 'failed']))
  assert.deepEqual(result.jobs.map(item => item.status), ['cancelling', 'failed', 'queued'])
  assert.equal(result.isGenerating, true)
  assert.deepEqual(jobs.map(item => item.status), ['running', 'failed', 'queued'])
})

test('Director slice keeps the public setter behavior while state is composed separately', async () => {
  const { createDirectorSlice } = await import('../src/stores/directorSlice.ts')
  let state
  const set = update => {
    const partial = typeof update === 'function' ? update(state) : update
    state = { ...state, ...partial }
  }
  state = createDirectorSlice(set)

  state.setDirectorMusicVideoTreatment({ generation_mode: 'direct_video' })
  assert.equal(state.directorMusicVideoTreatment.generation_mode, 'direct_video')
  assert.equal(state.directorSeamless, false)

  state.setDirectorVideoInferenceSteps('model-a', 100)
  assert.equal(state.directorVideoInferenceStepsByModel['model-a'], 50)
  state.setDirectorVideoInferenceSteps('model-a', null)
  assert.equal(state.directorVideoInferenceStepsByModel['model-a'], undefined)

  state.setDirectorAutoMode(false)
  assert.equal(state.directorAutoMode, false)
})

test('theme slice keeps mode and family persistence keys through the public facade', async () => {
  const { JSDOM } = await import('jsdom')
  const dom = new JSDOM('<!doctype html><html><head><meta name="theme-color"></head><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    localStorage: dom.window.localStorage,
  })
  const { createThemeSlice } = await import('../src/stores/themeSlice.ts')
  let state
  const set = update => {
    const partial = typeof update === 'function' ? update(state) : update
    state = { ...state, ...partial }
  }
  state = createThemeSlice(set, () => state)
  state.setThemeMode('light')
  assert.equal(state.themePrefs.mode, 'light')
  state.setThemeFamily('onyx')
  assert.equal(state.themePrefs.family, 'onyx')
  assert.equal(globalThis.localStorage.getItem('maestro-theme-mode'), 'light')
  assert.equal(globalThis.localStorage.getItem('maestro-theme-family'), 'onyx')

  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.getState().setThemeMode('auto')
  assert.equal(useStore.getState().themePrefs.mode, 'auto')
  assert.equal(globalThis.localStorage.getItem('maestro-theme-mode'), 'auto')
})

test('useStore keeps Director actions available through its existing public facade', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({ directorAutoMode: true, directorSeamless: true })
  useStore.getState().setDirectorMusicVideoTreatment({ generation_mode: 'direct_video' })
  assert.equal(useStore.getState().directorMusicVideoTreatment.generation_mode, 'direct_video')
  assert.equal(useStore.getState().directorSeamless, false)
  useStore.getState().setDirectorVideoInferenceSteps('characterization-model', 7.4)
  assert.equal(useStore.getState().directorVideoInferenceStepsByModel['characterization-model'], 7)
})
