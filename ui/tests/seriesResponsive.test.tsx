import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', {
  url: 'http://localhost/',
})
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: dom.window.navigator,
})

test('Series Lab mounts a mobile-first selector while retaining its desktop rail', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { SeriesLabPanel } = await import('../src/features/series/SeriesLabPanel.tsx')
  const { emptySeriesLibrary } = await import('../src/features/series/model.ts')
  const { useSeriesStore } = await import('../src/features/series/store.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  const workspace = 'responsive-test'
  useStore.setState({ activeWorkspace: workspace })
  useSeriesStore.setState({
    workspace,
    library: emptySeriesLibrary(workspace),
    activeSeriesId: '',
    activeEpisodeId: '',
    hydrated: true,
    loading: false,
    dirty: false,
    saving: false,
    error: null,
    planRecovery: [],
    renderRecovery: [],
  })

  try {
    render(<SeriesLabPanel />)
    const workspaceRegion = screen.getByRole('region', { name: 'Series Lab workspace' })
    const libraryRail = screen.getByRole('complementary', { name: 'Series library' })
    const projectSelector = screen.getByRole('navigation', { name: 'Series projects' })
    const episodeControls = screen.getByRole('group', { name: 'Episode controls' })

    assert.ok(workspaceRegion.classList.contains('flex-col'))
    assert.ok(workspaceRegion.classList.contains('md:flex-row'))
    assert.ok(libraryRail.classList.contains('w-full'))
    assert.ok(libraryRail.classList.contains('md:w-56'))
    assert.ok(projectSelector.classList.contains('overflow-x-auto'))
    assert.ok(projectSelector.classList.contains('md:overflow-y-auto'))
    assert.ok(episodeControls.classList.contains('flex-wrap'))
    assert.ok(screen.getByRole('button', { name: 'New' }))
    assert.ok(screen.getByRole('button', { name: 'Story' }))
    assert.ok(workspaceRegion.querySelector('.min-h-0.min-w-0.flex-1'))
  } finally {
    cleanup()
  }
})
