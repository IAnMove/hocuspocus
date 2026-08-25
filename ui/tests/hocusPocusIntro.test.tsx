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
    render(<HocusPocusIntro onComplete={() => { completed += 1 }} />)
    assert.ok(screen.getByRole('heading', { name: 'HocusPocus' }))
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }))
    await waitFor(() => assert.equal(completed, 1), { timeout: 900 })
  } finally {
    cleanup()
  }
})

test('intro auto-completes once even if onComplete identity changes', { concurrency: false }, async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { HocusPocusIntro, INTRO_DURATION_MS } = await import('../src/components/HocusPocusIntro.tsx')
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

  try {
    let completed = 0
    const { rerender } = render(<HocusPocusIntro onComplete={() => { completed += 1 }} />)
    rerender(<HocusPocusIntro onComplete={() => { completed += 1 }} />)
    rerender(<HocusPocusIntro onComplete={() => { completed += 1 }} />)
    const durationTimers = scheduled.filter(item => item.ms === INTRO_DURATION_MS)
    const doneTimers = scheduled.filter(item => item.ms === INTRO_DURATION_MS + 360)
    assert.equal(durationTimers.length, 1)
    assert.equal(doneTimers.length, 1)
    durationTimers[0].fn()
    doneTimers[0].fn()
    assert.equal(completed, 1)
  } finally {
    window.setTimeout = originalSet
    window.clearTimeout = originalClear
    cleanup()
  }
})
