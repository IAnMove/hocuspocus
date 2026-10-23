import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { InstallComponent, InstallStatus } from '../src/api/installManager.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Event: dom.window.Event,
    KeyboardEvent: dom.window.KeyboardEvent,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

const GB = 1024 ** 3

function component(id: string, patch: Partial<InstallComponent> = {}): InstallComponent {
  return {
    id, engine: id, title: id, summary: `${id} summary`, estimatedBytes: 6 * GB, restartRequired: false,
    state: 'not_installed', supported: true, reason: null, sizeBytes: 0, job: null, ...patch,
  }
}

function status(patch: Partial<InstallStatus> = {}): InstallStatus {
  return {
    launcher: { available: true, reason: null },
    disk: { freeBytes: 100 * GB, totalBytes: 500 * GB },
    base: { title: 'Studio', summary: '', estimatedBytes: 11 * GB, engine: 'wangp', installed: true, state: 'installed', sizeBytes: 11 * GB },
    components: [
      component('sam'),
      component('hunyuan3d', { state: 'installed', sizeBytes: 9 * GB, restartRequired: true }),
      component('rigging', { state: 'unsupported', supported: false, reason: 'Linux only' }),
    ],
    busy: null,
    ...patch,
  }
}

function mockServer(initial: InstallStatus) {
  const calls: string[] = []
  let current = initial
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    const ok = (body: unknown, code = 200) => new Response(JSON.stringify(body), { status: code })
    if (url.endsWith('/output?lines=40')) return ok({ lines: ['Collecting torch', '100%'] })
    if (init?.method === 'POST') return ok({ state: 'running' }, 202)
    return ok(current)
  }) as typeof fetch
  return { calls, set: (next: InstallStatus) => { current = next } }
}

async function mountPanel() {
  const { render, cleanup } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { InstallationPanel } = await import('../src/components/Installation/InstallationPanel.tsx')
  useStore.setState({ settingsOpen: true })
  return { view: render(<InstallationPanel />), cleanup }
}

test('lists the base and every component with its state and size', async () => {
  mockServer(status())
  const { view, cleanup } = await mountPanel()
  try {
    await view.findByTestId('install-row-sam')
    assert.match(view.getByTestId('install-row-sam').textContent ?? '', /Not installed.*about 6\.0 GB once installed/s)
    assert.match(view.getByTestId('install-row-hunyuan3d').textContent ?? '', /Installed.*9\.0 GB/s)
    assert.match(view.getByTestId('install-row-rigging').textContent ?? '', /Not available here.*Linux only/s)
    assert.match(view.container.textContent ?? '', /100\.0 GB free of 500\.0 GB/)
  } finally {
    cleanup()
  }
})

test('Install starts the component and refreshes the status', async () => {
  const server = mockServer(status())
  const { view, cleanup } = await mountPanel()
  try {
    const row = await view.findByTestId('install-row-sam')
    const { fireEvent, waitFor } = await import('@testing-library/react')
    fireEvent.click(row.querySelector('button')!)
    await waitFor(() => assert(server.calls.includes('POST /api/v1/system/install/sam/install')))
  } finally {
    cleanup()
  }
})

test('removing takes two clicks and never starts on the first', async () => {
  const server = mockServer(status())
  const { view, cleanup } = await mountPanel()
  try {
    const row = await view.findByTestId('install-row-hunyuan3d')
    const { fireEvent, waitFor } = await import('@testing-library/react')
    const remove = () => row.querySelector('button')!
    fireEvent.click(remove())
    assert.match(remove().textContent ?? '', /Click again to remove \(9\.0 GB\)/)
    assert(!server.calls.some(call => call.endsWith('/uninstall')))
    fireEvent.click(remove())
    await waitFor(() => assert(server.calls.includes('POST /api/v1/system/install/hunyuan3d/uninstall')))
  } finally {
    cleanup()
  }
})

test('while something installs, other rows wait and the installer output is followed', async () => {
  mockServer(status({
    busy: 'sam',
    components: [
      component('sam', { state: 'running', job: { component: 'sam', kind: 'install', state: 'running', startedAt: 1, finishedAt: null, code: null, message: null } }),
      component('hunyuan3d'),
    ],
  }))
  const { view, cleanup } = await mountPanel()
  try {
    await view.findByText(/A change is in progress/)
    assert.match((await view.findByTestId('install-row-sam')).textContent ?? '', /Installing\. This can take several minutes\./)
    await view.findByText(/Collecting torch/)
    const other = view.getByTestId('install-row-hunyuan3d')
    assert.equal(view.getAllByText(/A change is in progress/).length, 1, 'one banner, not one message per row')
    assert.equal(other.querySelector('button')!.hasAttribute('disabled'), true)
  } finally {
    cleanup()
  }
})

test('outside Pinokio install buttons are disabled and one banner says why', async () => {
  mockServer(status({ launcher: { available: false, reason: 'not_in_pinokio' } }))
  const { view, cleanup } = await mountPanel()
  try {
    const row = await view.findByTestId('install-row-sam')
    assert.equal(row.querySelector('button')!.hasAttribute('disabled'), true)
    assert.equal(view.getAllByText(/not started from Pinokio/).length, 1)
  } finally {
    cleanup()
  }
})

test('a stale base install says it needs an update instead of claiming it is missing', async () => {
  mockServer(status({ base: { ...status().base, installed: false, state: 'needs_update' } }))
  const { view, cleanup } = await mountPanel()
  try {
    await view.findByTestId('install-row-sam')
    assert.match(view.container.textContent ?? '', /Needs update/)
    assert.match(view.container.textContent ?? '', /Use Update in Pinokio/)
  } finally {
    cleanup()
  }
})
