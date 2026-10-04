import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { setUiLanguage } from '../src/i18n/index.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
    KeyboardEvent: dom.window.KeyboardEvent,
    MessageEvent: dom.window.MessageEvent,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function task(performance?: Record<string, unknown>) {
  return {
    id: 'task-generation-pace',
    root_id: 'task-generation-pace',
    parent_id: null,
    kind: 'video',
    title: 'Video generation',
    workflow: 'generation',
    status: 'running',
    phase: 'denoising',
    message: 'Denoising',
    detail: '',
    current: 4,
    total: 20,
    progress: 20,
    detail_current: 0,
    detail_total: 0,
    created_at: 1,
    queued_at: 1,
    started_at: 1,
    updated_at: 2,
    completed_at: null,
    attempt: 1,
    max_attempts: 1,
    cancelable: false,
    resumable: false,
    recoverable: true,
    metadata: performance ? { performance } : {},
  }
}

const barProps = {
  detailsOpen: false,
  liveCount: 1,
  clock: 10_000,
  primaryGroup: null,
  busyIds: new Set<string>(),
  toggleRef: { current: null },
  onToggle: () => undefined,
  onCopyPrompt: () => undefined,
  onControl: () => undefined,
}

test('activity bar shows the pace warning when the step time is degraded', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ActivityCompactBar } = await import('../src/features/activity/ActivityCompactBar.tsx')
  try {
    render(<ActivityCompactBar {...barProps} primary={task({ degraded: true })} />)
    const warning = screen.getByTestId('activity-memory-warning')
    assert.equal(warning.textContent, "Slower than this model's usual step time")
  } finally {
    cleanup()
  }
})

test('activity bar hides the pace warning without a degraded measurement', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ActivityCompactBar } = await import('../src/features/activity/ActivityCompactBar.tsx')
  try {
    const healthy = render(<ActivityCompactBar {...barProps} primary={task({ degraded: false })} />)
    assert.equal(screen.queryByTestId('activity-memory-warning'), null)
    healthy.unmount()
    render(<ActivityCompactBar {...barProps} primary={task()} />)
    assert.equal(screen.queryByTestId('activity-memory-warning'), null)
  } finally {
    cleanup()
  }
})

test('activity bar shows the Spanish pace warning', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ActivityCompactBar } = await import('../src/features/activity/ActivityCompactBar.tsx')
  await setUiLanguage('es')
  try {
    render(<ActivityCompactBar {...barProps} primary={task({ degraded: true })} />)
    assert.equal(
      screen.getByTestId('activity-memory-warning').textContent,
      'Más lento que el tiempo de paso habitual de este modelo',
    )
  } finally {
    cleanup()
    await setUiLanguage('en')
  }
})
