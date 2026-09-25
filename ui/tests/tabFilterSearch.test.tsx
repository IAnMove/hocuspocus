import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/',
  })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class {
      observe() {}
      disconnect() {}
    },
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  })
  Object.defineProperty(dom.window.HTMLElement.prototype, 'scrollIntoView', {
    configurable: true,
    value: () => undefined,
  })
  dom.window.requestAnimationFrame = callback => {
    callback(0)
    return 1
  }
  dom.window.cancelAnimationFrame = () => undefined
}

installDom()

test('primary navigation exposes four stable categories and highlights the selected context', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  useStore.setState({ developerMode: false, mediaFilter: 'all', outputSearchQuery: '', activeWorkspace: 'default', browsingUploads: false, sidebarOpen: false, sidebarMode: 'studio', settingsOpen: true, dashboardOpen: true, loadOutputs: async () => undefined })
  try {
    render(<TabFilter />)
    const direct = screen.getByRole('button', { name: 'Direct generation' })
    const studios = screen.getByRole('button', { name: 'Studios' })
    const production = screen.getByRole('button', { name: 'Production' })
    const media = screen.getByRole('button', { name: 'Media' })
    assert.ok(direct)
    assert.ok(studios)
    assert.ok(production)
    assert.equal(media.getAttribute('data-navigation-active'), 'true')
    assert.equal(screen.queryByRole('button', { name: 'Create' }), null)
    assert.equal(screen.queryByRole('button', { name: 'Library' }), null)
    assert.equal(document.querySelector('details'), null)
    assert.equal(document.querySelectorAll('.hp-navigation-children').length, 1)
    assert.ok(document.querySelector('.hp-navigation-children[data-navigation-category="media"]'))
    const outputFolder = screen.getByRole('button', { name: /Switch output folder: default/ })
    assert.equal(screen.getByRole('navigation').contains(outputFolder), true)
    assert.equal(outputFolder.closest('[class*="overflow-x-auto"]'), null)

    fireEvent.click(studios)
    fireEvent.click(screen.getByRole('tab', { name: 'Story Lab' }))
    assert.equal(useStore.getState().mediaFilter, 'stories')
    assert.equal(useStore.getState().settingsOpen, false)
    assert.equal(useStore.getState().dashboardOpen, false)
    assert.equal(studios.getAttribute('data-navigation-active'), 'true')
    assert.equal(media.hasAttribute('data-navigation-active'), false)

    fireEvent.click(direct)
    const directDestinations = [
      ['Image', 'image', 'images'],
      ['Video', 'video', 'videos'],
      ['Audio', 'audio', 'audio'],
      ['3D', 'model3d', 'model3d'],
      ['Edit', 'avatar', 'avatars'],
      ['Tools', 'tools', 'all'],
    ] as const
    for (const [label, mode, filter] of directDestinations) {
      fireEvent.click(screen.getByRole('tab', { name: label }))
      assert.equal(useStore.getState().generationMode, mode)
      assert.equal(useStore.getState().mediaFilter, filter)
      assert.equal(useStore.getState().sidebarMode, 'studio')
    }
    assert.equal(direct.getAttribute('data-navigation-active'), 'true')
    assert.equal(screen.getByRole('tab', { name: 'Tools' }).getAttribute('aria-selected'), 'true')
  } finally {
    cleanup()
  }
})

test('semantic Wizard navigation reveals the matching category without DOM-coordinate control', { concurrency: false }, async () => {
  const { render, screen, cleanup, act } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { announceWizardNavigation } = await import('../src/lib/navigationCategories.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  useStore.setState({ developerMode: false, mediaFilter: 'all', outputSearchQuery: '' })
  try {
    const view = render(<TabFilter />)
    await act(async () => { announceWizardNavigation('director') })
    const production = screen.getByRole('button', { name: 'Production' })
    assert.equal(production.getAttribute('data-navigation-active'), 'true')
    assert.equal(production.getAttribute('data-wizard-magic'), 'active')
    assert.ok(document.querySelector('.hp-navigation-children[data-navigation-category="production"]'))
    view.unmount()
  } finally {
    cleanup()
  }
})

test('navigation destinations map to visible categories', async () => {
  const { categoryForNavigationDestination, categoryForMediaFilter } = await import('../src/lib/navigationCategories.ts')
  assert.equal(categoryForNavigationDestination('studio'), 'direct-generation')
  assert.equal(categoryForNavigationDestination('story_lab'), 'studios')
  assert.equal(categoryForNavigationDestination('video_editor'), 'production')
  assert.equal(categoryForNavigationDestination('images'), 'media')
  assert.equal(categoryForNavigationDestination('settings'), null)
  assert.equal(categoryForMediaFilter('character-replacement'), 'studios')
  const { hidesDirectGenerationSidebar, revealDirectorWorkspace, visibleWorkspaceSurface } = await import('../src/lib/navigationCategories.ts')
  assert.equal(hidesDirectGenerationSidebar('scene3d', 'studio'), true)
  assert.equal(hidesDirectGenerationSidebar('stories', 'studio'), true)
  assert.equal(hidesDirectGenerationSidebar('characters', 'studio'), true)
  assert.equal(hidesDirectGenerationSidebar('videos', 'studio'), false)
  assert.equal(hidesDirectGenerationSidebar('comics', 'director'), false)
  assert.equal(hidesDirectGenerationSidebar('scene3d', 'director'), true)
  const revealed = { mediaFilter: 'stories' as const, sidebarMode: 'studio' as const, sidebarOpen: false }
  revealDirectorWorkspace({
    mediaFilter: revealed.mediaFilter,
    setSidebarMode: mode => { revealed.sidebarMode = mode },
    setSidebarOpen: open => { revealed.sidebarOpen = open },
    setMediaFilter: filter => { revealed.mediaFilter = filter },
  })
  assert.equal(revealed.sidebarMode, 'director')
  assert.equal(revealed.sidebarOpen, true)
  assert.equal(revealed.mediaFilter, 'all')
  assert.equal(hidesDirectGenerationSidebar(revealed.mediaFilter, revealed.sidebarMode), false)
  const comicDirector = { mediaFilter: 'comics' as const, sidebarMode: 'studio' as const, sidebarOpen: false }
  revealDirectorWorkspace({
    mediaFilter: comicDirector.mediaFilter,
    setSidebarMode: mode => { comicDirector.sidebarMode = mode },
    setSidebarOpen: open => { comicDirector.sidebarOpen = open },
    setMediaFilter: filter => { comicDirector.mediaFilter = filter },
  })
  assert.equal(comicDirector.mediaFilter, 'comics')
  assert.equal(visibleWorkspaceSurface({ mediaFilter: 'images', sidebarMode: 'studio', sidebarOpen: true }), 'generate')
  assert.equal(visibleWorkspaceSurface({ mediaFilter: 'images', sidebarMode: 'studio', sidebarOpen: false }), 'section')
  assert.equal(visibleWorkspaceSurface({ mediaFilter: 'stories', sidebarMode: 'studio', sidebarOpen: true }), 'section')
  assert.equal(visibleWorkspaceSurface({ mediaFilter: 'all', sidebarMode: 'director', sidebarOpen: true }), 'director')
  assert.equal(visibleWorkspaceSurface({ mediaFilter: 'videos', sidebarMode: 'studio', sidebarOpen: true, dashboardOpen: true }), 'section')
})

test('character replacement is a featured studio beside the video editors in both languages', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  ensureUiI18n()
  for (const language of ['en', 'es'] as const) {
    await setUiLanguage(language)
    useStore.setState({
      mediaFilter: 'all', outputSearchQuery: '', generationMode: 'avatar',
      sidebarMode: 'studio', sidebarOpen: true, settingsOpen: true, dashboardOpen: true,
      activeWorkspace: 'default', loadOutputs: async () => undefined,
    })
    try {
      render(<TabFilter />)
      const studios = screen.getByRole('button', { name: language === 'en' ? 'Studios' : 'Estudios' })
      fireEvent.click(studios)
      const replacement = screen.getByRole('tab', { name: language === 'en' ? 'Replace character' : 'Reemplazar personaje' })
      assert.equal(replacement.getAttribute('data-navigation-featured'), 'true')
      assert.equal(replacement.previousElementSibling?.textContent, language === 'en' ? 'Video 3D' : 'Vídeo 3D')
      fireEvent.click(screen.getByRole('tab', { name: language === 'en' ? 'Video 2.5D' : 'Vídeo 2,5D' }))
      assert.equal(useStore.getState().mediaFilter, 'scene3d')
      assert.equal(useStore.getState().sidebarOpen, false)
      fireEvent.click(replacement)
      assert.equal(useStore.getState().mediaFilter, 'character-replacement')
      assert.equal(useStore.getState().sidebarOpen, false)
      assert.equal(useStore.getState().settingsOpen, false)
      assert.equal(useStore.getState().dashboardOpen, false)
      assert.equal(replacement.getAttribute('aria-selected'), 'true')
      assert.equal(studios.getAttribute('data-navigation-active'), 'true')
      assert.equal(document.querySelectorAll('.hp-navigation-primary[data-navigation-category]').length, 4)
      assert.equal(document.querySelectorAll('.hp-navigation-children').length, 1)
    } finally {
      cleanup()
    }
  }
  await setUiLanguage('en')
})

test('opening Director from a studio leaves the studio so the sidebar can mount', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { hidesDirectGenerationSidebar } = await import('../src/lib/navigationCategories.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  useStore.setState({
    mediaFilter: 'stories', outputSearchQuery: '', generationMode: 'video',
    sidebarMode: 'studio', sidebarOpen: false, settingsOpen: false, dashboardOpen: false,
    activeWorkspace: 'default', loadOutputs: async () => undefined,
  })
  try {
    render(<TabFilter />)
    fireEvent.click(screen.getByRole('button', { name: 'Production' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Director' }))
    const state = useStore.getState()
    assert.equal(state.sidebarMode, 'director')
    assert.equal(state.sidebarOpen, true)
    assert.equal(state.mediaFilter, 'all')
    assert.equal(hidesDirectGenerationSidebar(state.mediaFilter, state.sidebarMode), false)
  } finally {
    cleanup()
  }
})

test('library filters leave Direct generation and Studios occupy the main workspace', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { visibleWorkspaceSurface } = await import('../src/lib/navigationCategories.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  useStore.setState({
    mediaFilter: 'all', outputSearchQuery: '', generationMode: 'image',
    sidebarMode: 'studio', sidebarOpen: true, settingsOpen: false, dashboardOpen: false,
    activeWorkspace: 'default', loadOutputs: async () => undefined,
  })
  try {
    render(<TabFilter />)
    fireEvent.click(screen.getByRole('button', { name: 'Media' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Images' }))
    assert.equal(useStore.getState().mediaFilter, 'images')
    assert.equal(useStore.getState().sidebarOpen, false)
    assert.equal(visibleWorkspaceSurface(useStore.getState()), 'section')
    fireEvent.click(screen.getByRole('button', { name: 'Direct generation' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Image' }))
    assert.equal(useStore.getState().generationMode, 'image')
    assert.equal(useStore.getState().sidebarOpen, true)
    assert.equal(visibleWorkspaceSurface(useStore.getState()), 'generate')
    fireEvent.click(screen.getByRole('button', { name: 'Studios' }))
    fireEvent.click(screen.getByRole('tab', { name: 'Story Lab' }))
    assert.equal(useStore.getState().mediaFilter, 'stories')
    assert.equal(visibleWorkspaceSurface(useStore.getState()), 'section')
  } finally { cleanup() }
})

test('settings and Director events still work when Direct generation is unmounted', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { WorkspaceEventBridge } = await import('../src/components/Sidebar/WorkspaceEventBridge.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { visibleWorkspaceSurface } = await import('../src/lib/navigationCategories.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  useStore.setState({
    mediaFilter: 'stories', outputSearchQuery: '', generationMode: 'video',
    sidebarMode: 'studio', sidebarOpen: false, settingsOpen: false, dashboardOpen: true,
    activeWorkspace: 'default', loadOutputs: async () => undefined,
  })
  try {
    render(<>
      <WorkspaceEventBridge />
      <TabFilter />
    </>)
    assert.equal(visibleWorkspaceSurface(useStore.getState()), 'section')
    fireEvent.click(screen.getByRole('button', { name: 'Settings' }))
    assert.equal(useStore.getState().settingsOpen, true)
    assert.equal(useStore.getState().dashboardOpen, false)
    useStore.setState({ settingsOpen: false, mediaFilter: 'stories', sidebarMode: 'studio', sidebarOpen: false })
    window.dispatchEvent(new Event('maestro:director-open'))
    const afterDirector = useStore.getState()
    assert.equal(afterDirector.sidebarMode, 'director')
    assert.equal(afterDirector.sidebarOpen, true)
    assert.equal(afterDirector.mediaFilter, 'all')
    assert.equal(visibleWorkspaceSurface(afterDirector), 'director')
    useStore.setState({ sidebarMode: 'director', sidebarOpen: false, mediaFilter: 'all', settingsOpen: false })
    window.dispatchEvent(new Event('hocuspocus:studio-open'))
    const afterStudio = useStore.getState()
    assert.equal(afterStudio.sidebarMode, 'studio')
    assert.equal(afterStudio.sidebarOpen, true)
    assert.equal(visibleWorkspaceSurface(afterStudio), 'generate')
  } finally { cleanup() }
})

test('favorites compact label stays empty instead of leaking the catalog key', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  useStore.setState({ developerMode: false, mediaFilter: 'all' })
  try {
    render(<TabFilter />)
    const favorites = screen.getByRole('tab', { name: /Favorites/i })
    assert.ok(favorites)
    assert.equal(favorites.textContent?.includes('short.favorites'), false)
  } finally {
    cleanup()
  }
})

test('video result filters are listed beside Videos', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  useStore.setState({ developerMode: false, mediaFilter: 'all' })
  try {
    render(<TabFilter />)
    assert.ok(screen.getByRole('tab', { name: /Videoclips/i }))
    assert.ok(screen.getByRole('tab', { name: /Trailers/i }))
    assert.ok(screen.getByRole('tab', { name: /Episodes/i }))
    assert.ok(screen.getByRole('tab', { name: 'Scenes' }))
    assert.ok(screen.getByRole('tab', { name: 'Style sheet' }))
    assert.ok(screen.getByRole('tab', { name: 'Edits' }))
    assert.ok(screen.getByRole('tab', { name: 'Multi-clip' }))
    assert.equal(screen.queryByRole('tab', { name: /Internal dev audit/i }), null)
  } finally {
    cleanup()
  }
})

test('navigation follows destinations changed outside the top bar', { concurrency: false }, async () => {
  const { render, screen, cleanup, act } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  useStore.setState({ developerMode: false, mediaFilter: 'all', sidebarOpen: false, dashboardOpen: false, loadOutputs: async () => undefined })
  try {
    render(<TabFilter />)
    await act(async () => { useStore.getState().setMediaFilter('stories') })
    assert.equal(screen.getByRole('button', { name: 'Studios' }).getAttribute('data-navigation-active'), 'true')
    assert.ok(document.querySelector('.hp-navigation-children[data-navigation-category="studios"]'))

    await act(async () => { useStore.getState().setDashboardOpen(true) })
    assert.equal(screen.getByRole('button', { name: 'Production' }).getAttribute('data-navigation-active'), 'true')
    assert.ok(document.querySelector('.hp-navigation-children[data-navigation-category="production"]'))
  } finally {
    useStore.setState({ dashboardOpen: false })
    cleanup()
  }
})

test('Auditoría interna is only listed in developer mode', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  useStore.setState({ developerMode: true, mediaFilter: 'all' })
  try {
    render(<TabFilter />)
    assert.ok(screen.getByRole('tab', { name: /Internal dev audit/i }))
  } finally {
    useStore.setState({ developerMode: false })
    cleanup()
  }
})

test('closing or unmounting search cancels its hidden debounce', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { TabFilter } = await import('../src/components/MainContent/TabFilter.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  ensureUiI18n()
  await setUiLanguage('en')
  const originalSetTimeout = window.setTimeout
  const originalClearTimeout = window.clearTimeout
  const timers = new Map<number, TimerHandler>()
  let timerId = 0
  let outputLoads = 0

  window.setTimeout = ((callback: TimerHandler) => {
    timerId += 1
    timers.set(timerId, callback)
    return timerId
  }) as typeof window.setTimeout
  window.clearTimeout = ((id: number | undefined) => {
    if (typeof id === 'number') timers.delete(id)
  }) as typeof window.clearTimeout
  useStore.setState({
    mediaFilter: 'all',
    outputSearchQuery: '',
    loadOutputs: async () => { outputLoads += 1 },
  })

  try {
    const view = render(<TabFilter />)
    fireEvent.click(screen.getByTitle('Search library'))
    const firstInput = screen.getByPlaceholderText('Search...') as HTMLInputElement
    fireEvent.change(firstInput, { target: { value: 'hidden query' } })
    assert.equal(firstInput.value, 'hidden query')
    assert.equal(timers.size, 1)

    fireEvent.click(screen.getByRole('button', { name: 'Close search' }))
    assert.equal(timers.size, 0)
    assert.equal(useStore.getState().outputSearchQuery, '')
    assert.equal(outputLoads, 0)

    fireEvent.click(screen.getByTitle('Search library'))
    fireEvent.change(screen.getByPlaceholderText('Search...'), {
      target: { value: 'unmounted query' },
    })
    assert.equal(timers.size, 1)
    view.unmount()
    assert.equal(timers.size, 0)
    assert.equal(useStore.getState().outputSearchQuery, '')
    assert.equal(outputLoads, 0)
  } finally {
    cleanup()
    window.setTimeout = originalSetTimeout
    window.clearTimeout = originalClearTimeout
  }
})
