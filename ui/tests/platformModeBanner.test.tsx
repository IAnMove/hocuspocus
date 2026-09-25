import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  localStorage: dom.window.localStorage,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const { render, waitFor, cleanup } = await import('@testing-library/react')

test('shows the Apple Silicon editing mode from the capabilities contract', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => ({
    ok: true,
    json: async () => ({
      platform: 'darwin',
      arch: 'arm64',
      profile: 'macos-arm64-core-remote',
      accelerators: { cuda: false, mps: true, metal: true },
      ui: { mode: 'macosCoreRemote', show_cuda_controls: false },
      capabilities: {},
    }),
  })) as typeof fetch
  try {
    const { PlatformModeBanner } = await import('../src/components/PlatformModeBanner.tsx')
    const view = render(<PlatformModeBanner />)
    await waitFor(() => {
      assert.match(view.container.textContent ?? '', /macOS · editing and remote providers/)
    })
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})

test('does not invent a macOS banner on the NVIDIA Linux profile', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () => ({
    ok: true,
    json: async () => ({
      platform: 'linux',
      arch: 'x86_64',
      profile: 'linux-nvidia-local',
      accelerators: { cuda: true, mps: false, metal: false },
      ui: { mode: 'nvidiaLocal', show_cuda_controls: true },
      capabilities: {},
    }),
  })) as typeof fetch
  try {
    const { PlatformModeBanner } = await import('../src/components/PlatformModeBanner.tsx')
    const view = render(<PlatformModeBanner />)
    await waitFor(() => {
      assert.equal(view.container.textContent ?? '', '')
    })
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})
