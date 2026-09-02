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
  useStore.setState({ developerMode: false, mediaFilter: 'all', outputSearchQuery: '', activeWorkspace: 'default', browsingUploads: false, sidebarOpen: false, sidebarMode: 'studio', dashboardOpen: false, loadOutputs: async () => undefined })
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
  const { categoryForNavigationDestination } = await import('../src/lib/navigationCategories.ts')
  assert.equal(categoryForNavigationDestination('studio'), 'direct-generation')
  assert.equal(categoryForNavigationDestination('story_lab'), 'studios')
  assert.equal(categoryForNavigationDestination('video_editor'), 'production')
  assert.equal(categoryForNavigationDestination('images'), 'media')
  assert.equal(categoryForNavigationDestination('settings'), null)
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
    fireEvent.click(screen.getByTitle('Search outputs'))
    const firstInput = screen.getByPlaceholderText('Search...') as HTMLInputElement
    fireEvent.change(firstInput, { target: { value: 'hidden query' } })
    assert.equal(firstInput.value, 'hidden query')
    assert.equal(timers.size, 1)

    fireEvent.click(screen.getByRole('button', { name: 'Close search' }))
    assert.equal(timers.size, 0)
    assert.equal(useStore.getState().outputSearchQuery, '')
    assert.equal(outputLoads, 0)

    fireEvent.click(screen.getByTitle('Search outputs'))
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
