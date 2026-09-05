import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('Director dashboard lazy overlay stays absent until opened, then mounts its dialog', async () => {
  const { render, screen, act, cleanup } = await import('@testing-library/react')
  const { LazyDirectorOverlay } = await import('../src/App.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  act(() => useStore.setState({
    dashboardOpen: false,
    dashboardLoading: false,
    dashboardLoadError: null,
    dashboardPipelineList: [],
    dashboardSelectedPipeline: null,
  }))
  const view = render(<LazyDirectorOverlay open={false} />)
  assert.equal(screen.queryByRole('dialog', { name: 'Director video workflows' }), null)

  act(() => useStore.setState({ dashboardOpen: true }))
  view.rerender(<LazyDirectorOverlay open />)
  assert.ok(await screen.findByRole('dialog', { name: 'Director video workflows' }))
  cleanup()
})
