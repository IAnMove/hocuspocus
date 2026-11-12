import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
  localStorage: dom.window.localStorage,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('the profile notice names the providers in use, opens Settings and stays closed once dismissed', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { ProductionProfileNotice } = await import('../src/components/ProductionProfileNotice.tsx')
  const opened: boolean[] = []
  useStore.setState({
    productionProfileLoaded: true,
    productionProfileConfigured: false,
    productionProfileInvalidReason: '',
    setSettingsOpen: (open: boolean) => { opened.push(open) },
  })
  try {
    render(<ProductionProfileNotice />)
    const notice = screen.getByTestId('production-profile-notice')
    assert.match(notice.textContent || '', /MiniMax-M3 \(minimax\)/)
    fireEvent.click(screen.getByRole('button', { name: 'Choose providers' }))
    assert.deepEqual(opened, [true])
    assert.equal(screen.queryByTestId('production-profile-notice'), null)
    cleanup()
    render(<ProductionProfileNotice />)
    assert.equal(screen.queryByTestId('production-profile-notice'), null)      // dismissed for these defaults
  } finally {
    cleanup()
  }
})

test('a saved profile that cannot be read is said, not hidden', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { ProductionProfileNotice } = await import('../src/components/ProductionProfileNotice.tsx')
  useStore.setState({ productionProfileLoaded: true, productionProfileConfigured: false, productionProfileInvalidReason: 'text.model is required' })
  try {
    render(<ProductionProfileNotice />)
    assert.match(screen.getByTestId('production-profile-notice').textContent || '', /could not be read \(text\.model is required\)/)
  } finally {
    cleanup()
  }
})
