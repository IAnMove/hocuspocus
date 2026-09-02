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
    assert.equal(screen.queryByRole('tab', { name: /Internal dev audit/i }), null)
  } finally {
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
