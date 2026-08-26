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
  const { HocusPocusIntro, INTRO_DURATION_MS } = await import('../src/components/HocusPocusIntro.tsx')
  let completed = 0

  try {
    assert.equal(INTRO_DURATION_MS, 4500)
    render(<HocusPocusIntro onComplete={() => { completed += 1 }} version="1.2.3" />)
    assert.ok(screen.getByRole('heading', { name: 'HocusPocus' }))
    assert.ok(screen.getByText('v1.2.3'))
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }))
    await waitFor(() => assert.equal(completed, 1), { timeout: 1200 })
  } finally {
    cleanup()
  }
})

test('intro auto-completes once even if onComplete identity changes', { concurrency: false }, async () => {
  const { render, waitFor, cleanup } = await import('@testing-library/react')
  const { HocusPocusIntro, INTRO_DURATION_MS, INTRO_FADE_MS, INTRO_ASSET_TIMEOUT_MS } =
    await import('../src/components/HocusPocusIntro.tsx')
  const scheduled: { handle: number, fn: () => void, ms: number }[] = []
  let nextHandle = 1
  const originalSet = window.setTimeout
  const originalClear = window.clearTimeout
  window.setTimeout = ((fn: TimerHandler, ms?: number) => {
    const handle = nextHandle++
    scheduled.push({ handle, fn: fn as () => void, ms: Number(ms) || 0 })
    return handle as unknown as number
  }) as typeof window.setTimeout
  window.clearTimeout = ((handle: number) => {
    const index = scheduled.findIndex(item => item.handle === handle)
    if (index >= 0) scheduled.splice(index, 1)
  }) as typeof window.clearTimeout
  const at = (ms: number) => scheduled.filter(item => item.ms === ms)

  try {
    let completed = 0
    const { rerender } = render(<HocusPocusIntro onComplete={() => { completed += 1 }} />)
    rerender(<HocusPocusIntro onComplete={() => { completed += 1 }} />)
    rerender(<HocusPocusIntro onComplete={() => { completed += 1 }} />)

    // The hold does not start at mount: it starts once the key art has
    // decoded. Until then the only pending timer is the safety cap.
    assert.equal(at(INTRO_DURATION_MS).length, 0)
    assert.equal(at(INTRO_ASSET_TIMEOUT_MS).length, 1)

    await waitFor(() => assert.equal(at(INTRO_DURATION_MS).length, 1))
    assert.equal(at(INTRO_DURATION_MS + INTRO_FADE_MS).length, 1)

    at(INTRO_DURATION_MS)[0].fn()
    at(INTRO_DURATION_MS + INTRO_FADE_MS)[0].fn()
    assert.equal(completed, 1)
  } finally {
    window.setTimeout = originalSet
    window.clearTimeout = originalClear
    cleanup()
  }
})

test('intro holds the plate back until the art is ready', { concurrency: false }, async () => {
  const { render, waitFor, cleanup } = await import('@testing-library/react')
  const { HocusPocusIntro } = await import('../src/components/HocusPocusIntro.tsx')

  try {
    const { container } = render(<HocusPocusIntro onComplete={() => {}} />)
    const root = container.querySelector('.hp-intro-root')
    assert.ok(root)
    // data-run gates every keyframe in index.css, so the choreography
    // cannot play against an empty frame on a cold cache.
    assert.equal(root.getAttribute('data-run'), 'false')
    await waitFor(() => assert.equal(root.getAttribute('data-run'), 'true'))
    assert.equal(root.getAttribute('data-leaving'), 'false')
  } finally {
    cleanup()
  }
})
