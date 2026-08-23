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
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: dom.window.navigator,
  })
}

installDom()

function throwingStorage(): Storage {
  return {
    get length() { return 0 },
    clear() { throw new Error('storage blocked') },
    getItem() { throw new Error('storage blocked') },
    key() { throw new Error('storage blocked') },
    removeItem() { throw new Error('storage blocked') },
    setItem() { throw new Error('storage blocked') },
  }
}

test('WelcomeModal renders and dismisses when localStorage throws', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { safeStorageGet, safeStorageRemove } = await import('../src/lib/safeStorage.ts')
  const { WelcomeModal } = await import('../src/components/WelcomeModal.tsx')
  const original = window.localStorage
  Object.defineProperty(window, 'localStorage', { configurable: true, value: throwingStorage() })
  safeStorageRemove('local', 'maestro_welcome_seen_v1')

  try {
    render(<WelcomeModal />)
    assert.ok(screen.getByText('Welcome to Loreframe Lab'))
    fireEvent.click(screen.getByRole('button', { name: 'Get started' }))
    assert.equal(screen.queryByText('Welcome to Loreframe Lab'), null)
    assert.equal(safeStorageGet('local', 'maestro_welcome_seen_v1'), '1')
  } finally {
    cleanup()
    Object.defineProperty(window, 'localStorage', { configurable: true, value: original })
  }
})

test('PreflightBanner renders and dismisses when sessionStorage throws', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { safeStorageGet, safeStorageRemove } = await import('../src/lib/safeStorage.ts')
  const { PreflightBanner } = await import('../src/components/PreflightBanner.tsx')
  const originalStorage = window.sessionStorage
  const originalFetch = globalThis.fetch
  Object.defineProperty(window, 'sessionStorage', { configurable: true, value: throwingStorage() })
  safeStorageRemove('session', 'maestro_preflight_dismissed')
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => ({
      ok: false,
      checks: [{ id: 'ffmpeg', level: 'error', message: 'ffmpeg is missing' }],
    }),
  }) as Response

  try {
    render(<PreflightBanner />)
    await waitFor(() => assert.ok(screen.getByText('ffmpeg is missing')))
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
    assert.equal(screen.queryByText('ffmpeg is missing'), null)
    assert.equal(safeStorageGet('session', 'maestro_preflight_dismissed'), '1')
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
    Object.defineProperty(window, 'sessionStorage', { configurable: true, value: originalStorage })
  }
})

test('a successful external browser-storage removal is not replaced by stale memory', { concurrency: false }, async () => {
  const { safeStorageGet, safeStorageRemove, safeStorageSet } = await import('../src/lib/safeStorage.ts')
  const key = 'storage_external_removal_test'
  safeStorageRemove('local', key)

  safeStorageSet('local', key, 'persisted')
  assert.equal(safeStorageGet('local', key), 'persisted')

  window.localStorage.removeItem(key)
  assert.equal(safeStorageGet('local', key), null)
})

test('a quota failure retains the value in memory when browser storage reports it absent', { concurrency: false }, async () => {
  const { safeStorageGet, safeStorageRemove, safeStorageSet } = await import('../src/lib/safeStorage.ts')
  const original = window.localStorage
  const key = 'storage_quota_fallback_test'
  const quotaStorage: Storage = {
    get length() { return 0 },
    clear() {},
    getItem() { return null },
    key() { return null },
    removeItem() {},
    setItem() { throw new DOMException('Quota exceeded', 'QuotaExceededError') },
  }
  Object.defineProperty(window, 'localStorage', { configurable: true, value: quotaStorage })
  safeStorageRemove('local', key)

  try {
    safeStorageSet('local', key, 'memory-only')
    assert.equal(safeStorageGet('local', key), 'memory-only')
  } finally {
    safeStorageRemove('local', key)
    Object.defineProperty(window, 'localStorage', { configurable: true, value: original })
  }
})
