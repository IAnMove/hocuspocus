import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('HocusPocus intro identifies the studio and can be skipped', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { HocusPocusIntro } = await import('../src/components/HocusPocusIntro.tsx')
  let completed = 0

  try {
    render(<HocusPocusIntro onComplete={() => { completed += 1 }} />)
    assert.ok(screen.getByRole('heading', { name: 'HocusPocus' }))
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }))
    await waitFor(() => assert.equal(completed, 1), { timeout: 900 })
  } finally {
    cleanup()
  }
})
