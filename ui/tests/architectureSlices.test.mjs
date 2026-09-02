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
  state = createDirectorSlice(set, () => state)

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

test('settings slice toggles open and tab through the public facade', async () => {
  const { createSettingsSlice } = await import('../src/stores/settingsSlice.ts')
  let state
  const set = update => {
    const partial = typeof update === 'function' ? update(state) : update
    state = { ...state, ...partial }
  }
  state = createSettingsSlice(set, () => state)
  assert.equal(state.settingsOpen, false)
  assert.equal(state.settingsTab, 'performance')
  state.toggleSettings()
  assert.equal(state.settingsOpen, true)
  state.setSettingsTab('integrations')
  assert.equal(state.settingsTab, 'integrations')
  state.setSettingsOpen(false)
  assert.equal(state.settingsOpen, false)

  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.getState().setSettingsOpen(true)
  useStore.getState().setSettingsTab('integrations')
  assert.equal(useStore.getState().settingsOpen, true)
  assert.equal(useStore.getState().settingsTab, 'integrations')
  useStore.getState().toggleSettings()
  assert.equal(useStore.getState().settingsOpen, false)
  useStore.getState().openModelVisibility('video')
  assert.equal(useStore.getState().settingsOpen, true)
  assert.equal(useStore.getState().settingsTab, 'performance')
  assert.equal(useStore.getState().modelVisibilityFocus, 'video')
  useStore.getState().clearModelVisibilityFocus()
  assert.equal(useStore.getState().modelVisibilityFocus, null)
})

test('sidebar slice toggles open through the public facade', async () => {
  const { createSidebarSlice } = await import('../src/stores/sidebarSlice.ts')
  let state
  const set = update => {
    const partial = typeof update === 'function' ? update(state) : update
    state = { ...state, ...partial }
  }
  state = createSidebarSlice(set, () => state)
  assert.equal(state.sidebarOpen, false)
  state.toggleSidebar()
  assert.equal(state.sidebarOpen, true)
  state.setSidebarOpen(false)
  assert.equal(state.sidebarOpen, false)

  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.getState().setSidebarOpen(true)
  assert.equal(useStore.getState().sidebarOpen, true)
  useStore.getState().toggleSidebar()
  assert.equal(useStore.getState().sidebarOpen, false)
})

test('retake dialog slice opens and closes through the public facade', async () => {
  const { createRetakeDialogSlice } = await import('../src/stores/retakeDialogSlice.ts')
  let state
  const set = update => {
    const partial = typeof update === 'function' ? update(state) : update
    state = { ...state, ...partial }
  }
  state = createRetakeDialogSlice(set, () => state)
  assert.equal(state.retakeDialogOpen, false)
  assert.equal(state.retakeSourceFile, null)
  state.openRetakeDialog('clip.mp4')
  assert.equal(state.retakeDialogOpen, true)
  assert.equal(state.retakeSourceFile, 'clip.mp4')
  state.closeRetakeDialog()
  assert.equal(state.retakeDialogOpen, false)
  assert.equal(state.retakeSourceFile, null)

  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.getState().openRetakeDialog('source.mp4')
  assert.equal(useStore.getState().retakeDialogOpen, true)
  assert.equal(useStore.getState().retakeSourceFile, 'source.mp4')
  useStore.getState().closeRetakeDialog()
  assert.equal(useStore.getState().retakeDialogOpen, false)
  assert.equal(useStore.getState().retakeSourceFile, null)
})

test('developer-mode slice persists the local flag through the public facade', async () => {
  if (!globalThis.localStorage) {
    const { JSDOM } = await import('jsdom')
    const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
    Object.assign(globalThis, {
      window: dom.window,
      document: dom.window.document,
      localStorage: dom.window.localStorage,
    })
  }
  globalThis.localStorage.removeItem('hocuspocus-developer-mode-v1')

  const { createDeveloperModeSlice } = await import('../src/stores/developerModeSlice.ts')
  let state
  const set = update => {
    const partial = typeof update === 'function' ? update(state) : update
    state = { ...state, ...partial }
  }
  state = createDeveloperModeSlice(set, () => state)
  assert.equal(state.developerMode, false)
  state.setDeveloperMode(true)
  assert.equal(state.developerMode, true)
  assert.equal(globalThis.localStorage.getItem('hocuspocus-developer-mode-v1'), '1')

  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.getState().setDeveloperMode(true)
  assert.equal(useStore.getState().developerMode, true)
  assert.equal(globalThis.localStorage.getItem('hocuspocus-developer-mode-v1'), '1')
  useStore.getState().setDeveloperMode(false)
  assert.equal(useStore.getState().developerMode, false)
  assert.equal(globalThis.localStorage.getItem('hocuspocus-developer-mode-v1'), null)

  useStore.setState({ mediaFilter: 'auditdev', developerMode: true })
  useStore.getState().setDeveloperMode(false)
  assert.equal(useStore.getState().developerMode, false)
  assert.equal(useStore.getState().mediaFilter, 'all')

  useStore.setState({ mediaFilter: 'videos' })
  useStore.getState().setDeveloperMode(true)
  assert.equal(useStore.getState().developerMode, true)
  assert.equal(useStore.getState().mediaFilter, 'videos')

  const isolated = createDeveloperModeSlice(set, () => state)
  isolated.setDeveloperMode(false)
  assert.equal('mediaFilter' in isolated, false)
})

test('gallery slice keeps workspace and output filters through the public facade', async () => {
  const { createGallerySlice, galleryWorkspaceName } = await import('../src/stores/gallerySlice.ts')
  let state
  const set = update => {
    const partial = typeof update === 'function' ? update(state) : update
    state = { ...state, ...partial }
  }
  state = createGallerySlice(set, () => state)
  assert.equal(state.activeWorkspace, 'default')
  assert.equal(state.browsingUploads, false)
  assert.equal(state.mediaFilter, 'all')
  assert.equal(galleryWorkspaceName(state), 'default')
  assert.equal(galleryWorkspaceName({ activeWorkspace: 'film', browsingUploads: true }), '__uploads__')

  const image = {
    name: 'still.png', url: '/still.png', type: 'image', mode: null, edit_sub_mode: null,
    result_kind: null, favorite: false, size: 1, created_at: 1, completed_at: 1,
    completion_time_source: 'file', thumbnail_url: null,
  }
  const video = {
    name: 'clip.mp4', url: '/clip.mp4', type: 'video', mode: null, edit_sub_mode: null,
    result_kind: null, favorite: true, size: 2, created_at: 2, completed_at: 2,
    completion_time_source: 'file', thumbnail_url: null,
  }
  set({ outputs: [image, video], mediaFilter: 'images' })
  assert.deepEqual(state.filteredOutputs().map(item => item.name), ['still.png'])
  set({ mediaFilter: 'favorites' })
  assert.deepEqual(state.filteredOutputs().map(item => item.name), ['clip.mp4'])
  set({ galleryToast: { id: 1, message: 'ready' } })
  state.clearGalleryToast()
  assert.equal(state.galleryToast, null)
  state.setGalleryFeedAtTop(false)
  assert.equal(state.galleryFeedAtTop, false)

  const isolated = createGallerySlice(set, () => state)
  assert.equal('settingsOpen' in isolated, false)
  assert.equal('startGeneration' in isolated, false)
  assert.equal('loadSettingsFromOutput' in isolated, false)
  assert.equal('loadLlm' in isolated, false)

  const { useStore } = await import('../src/stores/useStore.ts')
  useStore.setState({
    mediaFilter: 'all',
    selectedOutput: 3,
    galleryToast: { id: 2, message: 'x' },
    galleryFeedAtTop: true,
  })
  useStore.getState().clearGalleryToast()
  assert.equal(useStore.getState().galleryToast, null)
  useStore.getState().setMediaFilter('videos')
  assert.equal(useStore.getState().mediaFilter, 'videos')
  assert.equal(useStore.getState().selectedOutput, 0)
  assert.equal(useStore.getState().galleryFeedAtTop, true)
})

test('LLM slice keeps status, models and enhance through the public facade', async () => {
  const { createLlmSlice } = await import('../src/stores/llmSlice.ts')
  let state
  const set = update => {
    const partial = typeof update === 'function' ? update(state) : update
    state = { ...state, ...partial }
  }
  state = createLlmSlice(set, () => state)
  assert.equal(state.llmStatus, null)
  assert.equal(state.llmLoading, false)
  assert.deepEqual(state.llmModels, [])
  assert.equal(state.isEnhancing, false)
  assert.equal(state.h3WindowPlan, null)

  const window = {
    index: 1,
    title: 'open',
    start_frame: 0,
    end_frame: 24,
    start_seconds: 0,
    end_seconds: 1,
    opening_state: '',
    closing_state: '',
    prompt: 'a man walks',
  }
  set({
    h3WindowPlan: {
      source_prompt: 'walk',
      signature: 'sig',
      planned_by: 'llm',
      total_frames: 24,
      window_frames: 24,
      window_count: 1,
      resolution: '540p',
      model_type: 'minimax_h3',
      windows: [window],
      window_prompts: [window.prompt],
    },
  })
  state.updateH3WindowPrompt(0, 'a woman walks')
  assert.equal(state.h3WindowPlan.windows[0].prompt, 'a woman walks')
  assert.deepEqual(state.h3WindowPlan.window_prompts, ['a woman walks'])
  state.updateH3WindowPrompt(-1, 'ignored')
  assert.equal(state.h3WindowPlan.windows[0].prompt, 'a woman walks')
  state.clearH3WindowPlan()
  assert.equal(state.h3WindowPlan, null)

  const isolated = createLlmSlice(set, () => state)
  assert.equal('startGeneration' in isolated, false)
  assert.equal('stopGeneration' in isolated, false)
  assert.equal('settingsOpen' in isolated, false)
  assert.equal('reconnectJobs' in isolated, false)

  const { useStore } = await import('../src/stores/useStore.ts')
  assert.equal(typeof useStore.getState().loadLlmStatus, 'function')
  assert.equal(typeof useStore.getState().loadLlmModels, 'function')
  assert.equal(typeof useStore.getState().loadLlm, 'function')
  assert.equal(typeof useStore.getState().unloadLlm, 'function')
  assert.equal(typeof useStore.getState().enhancePrompt, 'function')
  assert.equal(typeof useStore.getState().updateH3WindowPrompt, 'function')
  assert.equal(typeof useStore.getState().clearH3WindowPlan, 'function')
  useStore.getState().clearH3WindowPlan()
  assert.equal(useStore.getState().h3WindowPlan, null)
})

test('composed slices bind without as-never casts at the useStore call site', async () => {
  const fs = await import('node:fs/promises')
  const source = await fs.readFile(new URL('../src/stores/useStore.ts', import.meta.url), 'utf8')
  const composition = source.split('export const useStore')[1].split('generationMode:')[0]
  assert.match(composition, /bindSlice\(set, get, createSettingsSlice\)/)
  assert.match(composition, /bindSlice\(set, get, createThemeSlice\)/)
  assert.match(composition, /bindSlice\(set, get, createGallerySlice\)/)
  assert.match(composition, /bindSlice\(set, get, createLlmSlice\)/)
  assert.doesNotMatch(composition, /as never/)
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
