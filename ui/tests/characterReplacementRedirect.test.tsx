import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import { createElement } from 'react'
import { act, render } from '@testing-library/react'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

test('opening the old character-replacement id selects Edit › Replace character', async () => {
  const { openCharacterReplacement, characterReplacementReady } = await import('../src/features/characterReplacement/openCharacterReplacement.ts')
  const state = {
    generationMode: 'video' as const,
    editSubMode: 'retake' as const,
    mediaFilter: 'character-replacement' as const,
    sidebarMode: 'director' as const,
    sidebarOpen: false,
    settingsOpen: true,
    dashboardOpen: true,
    setGenerationMode(mode: 'avatar') { state.generationMode = mode },
    setEditSubMode(mode: 'replace_character') { state.editSubMode = mode },
    setMediaFilter(filter: typeof state.mediaFilter) { state.mediaFilter = filter },
    setSidebarMode(mode: 'studio') { state.sidebarMode = mode },
    setSidebarOpen(open: boolean) { state.sidebarOpen = open },
    setSettingsOpen(open: boolean) { state.settingsOpen = open },
    setDashboardOpen(open: boolean) { state.dashboardOpen = open },
  }
  openCharacterReplacement(state)
  assert.equal(characterReplacementReady(state), true)
  openCharacterReplacement(state)
  assert.equal(state.generationMode, 'avatar')
})

test('Wizard and MCP open_tab accepts character_replacement and the old hyphen id', { concurrency: false }, async () => {
  const { getCapability } = await import('../src/features/agent/capabilityRegistry.ts')
  const { defaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { characterReplacementReady } = await import('../src/features/characterReplacement/openCharacterReplacement.ts')
  assert.deepEqual(
    getCapability('open_tab')!.resolve({ type: 'open_tab', tab: 'character-replacement' }),
    { type: 'open_tab', tab: 'character_replacement' },
  )
  assert.deepEqual(
    getCapability('open_tab')!.resolve({ type: 'open_tab', tab: 'character_replacement' }),
    { type: 'open_tab', tab: 'character_replacement' },
  )
  const original = {
    setGenerationMode: useStore.getState().setGenerationMode,
    setEditSubMode: useStore.getState().setEditSubMode,
    setMediaFilter: useStore.getState().setMediaFilter,
  }
  useStore.setState({
    generationMode: 'video',
    editSubMode: 'retake',
    mediaFilter: 'images',
    sidebarMode: 'director',
    sidebarOpen: false,
    settingsOpen: true,
    dashboardOpen: true,
    setGenerationMode: mode => { useStore.setState({ generationMode: mode }) },
    setEditSubMode: mode => { useStore.setState({ editSubMode: mode }) },
    setMediaFilter: filter => { useStore.setState({ mediaFilter: filter }) },
    loadOutputs: async () => undefined,
  })
  try {
    const outcome = await defaultApplicationAdapters.openTab('character_replacement')
    assert.equal(characterReplacementReady(useStore.getState()), true)
    assert.equal(outcome.target?.id, 'character_replacement')
  } finally {
    useStore.setState({
      ...original,
      mediaFilter: 'all',
      generationMode: 'image',
      editSubMode: 'retake',
      sidebarOpen: false,
      settingsOpen: false,
      dashboardOpen: false,
      sidebarMode: 'studio',
    })
  }
})

test('the old filter opens Replace character once, and Director can leave it', { concurrency: false }, async () => {
  const { useCharacterReplacementRedirect, characterReplacementReady } = await import('../src/features/characterReplacement/openCharacterReplacement.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  const original = {
    setGenerationMode: useStore.getState().setGenerationMode,
    setEditSubMode: useStore.getState().setEditSubMode,
    setMediaFilter: useStore.getState().setMediaFilter,
    setSidebarMode: useStore.getState().setSidebarMode,
    setSidebarOpen: useStore.getState().setSidebarOpen,
    setSettingsOpen: useStore.getState().setSettingsOpen,
    setDashboardOpen: useStore.getState().setDashboardOpen,
  }
  function Probe() {
    useCharacterReplacementRedirect()
    return null
  }
  useStore.setState({
    generationMode: 'video',
    editSubMode: 'retake',
    mediaFilter: 'images',
    sidebarMode: 'director',
    sidebarOpen: false,
    settingsOpen: true,
    dashboardOpen: true,
    setGenerationMode: mode => { useStore.setState({ generationMode: mode }) },
    setEditSubMode: mode => { useStore.setState({ editSubMode: mode }) },
    setMediaFilter: filter => { useStore.setState({ mediaFilter: filter }) },
    setSidebarMode: mode => { useStore.setState({ sidebarMode: mode }) },
    setSidebarOpen: open => { useStore.setState({ sidebarOpen: open }) },
    setSettingsOpen: open => { useStore.setState({ settingsOpen: open }) },
    setDashboardOpen: open => { useStore.setState({ dashboardOpen: open }) },
  })
  try {
    render(createElement(Probe))
    assert.equal(useStore.getState().editSubMode, 'retake')
    await act(async () => {
      useStore.setState({ mediaFilter: 'character-replacement' })
    })
    assert.equal(characterReplacementReady(useStore.getState()), true)
    await act(async () => {
      useStore.setState({ sidebarMode: 'director' })
    })
    assert.equal(useStore.getState().sidebarMode, 'director')
    assert.equal(useStore.getState().mediaFilter, 'character-replacement')
    assert.equal(characterReplacementReady(useStore.getState()), false)
  } finally {
    useStore.setState({
      ...original,
      mediaFilter: 'all',
      generationMode: 'image',
      editSubMode: 'retake',
      sidebarOpen: false,
      settingsOpen: false,
      dashboardOpen: false,
      sidebarMode: 'studio',
    })
  }
})
