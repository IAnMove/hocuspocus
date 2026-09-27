import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const original = globalThis.fetch
const collection = (id: string, dependencies: string[]) => ({ id, dependencies, size: 1024 ** 2, download_size: 1024 ** 2, archive_size: 1024 ** 2, installed: false, cached: false, gallery: false })

test('download is explicit, shared dependencies count once, cancellation is explicit', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { ExampleDownloads } = await import('../src/features/scene3d/ExampleDownloads')
  const calls: { url: string; options?: RequestInit }[] = []
  const catalog = { collections: [collection('a', ['a', 'shared']), collection('b', ['b', 'shared']), collection('shared', ['shared'])], job: null as unknown }
  globalThis.fetch = (async (url, options) => {
    calls.push({ url: String(url), options })
    if (options?.method === 'POST') {
      catalog.job = { id: 'job', status: 'running', received: 0, total: 3 * 1024 ** 2, error: null }
      return new Response(JSON.stringify(catalog.job))
    }
    return new Response(JSON.stringify(catalog))
  }) as typeof fetch
  try {
    render(<ExampleDownloads required={['a', 'b']} />)
    await waitFor(() => assert.ok(screen.getByRole('button', { name: /3.0 MiB/ })))
    assert.ok(calls.every(call => !call.options?.method))
    fireEvent.click(screen.getByRole('button', { name: /3.0 MiB/ }))
    await waitFor(() => assert.ok(screen.getByRole('button', { name: 'Cancel download' })))
    const request = calls.find(call => call.options?.method === 'POST')!
    assert.equal(request.url, '/api/v1/examples/install')
    assert.deepEqual(JSON.parse(String(request.options?.body)), { collections: ['a', 'b'] })
    assert.equal((request.options?.headers as Record<string, string>)['X-Hocus-Action'], 'install-examples')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel download' }))
    await waitFor(() => assert.ok(calls.some(call => call.options?.method === 'DELETE' && call.url.endsWith('/job'))))
  } finally { cleanup(); globalThis.fetch = original }
})

test('offline catalog can retry and completed installs reload the current scene once', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { ExampleDownloads } = await import('../src/features/scene3d/ExampleDownloads')
  let offline = true, complete = false, reloaded = 0
  const pack = collection('a', ['a'])
  globalThis.fetch = (async () => {
    if (offline) throw new Error('offline')
    return new Response(JSON.stringify({ collections: [{ ...pack, installed: complete, cached: complete }], job: complete ? { id: 'finished', status: 'complete', received: 1, total: 1, error: null } : null }))
  }) as typeof fetch
  try {
    render(<ExampleDownloads required={['a']} onInstalled={() => { reloaded++ }} />)
    await waitFor(() => assert.ok(screen.getByRole('alert')))
    offline = false
    fireEvent.click(screen.getByRole('button', { name: 'Refresh / retry' }))
    await waitFor(() => assert.ok(screen.queryByRole('alert') === null))
    complete = true
    await waitFor(() => assert.equal(reloaded, 1), { timeout: 3500 })
    assert.ok(screen.getByRole('status').textContent?.includes('offline'))
    assert.ok(screen.queryByRole('button', { name: /Download/ }) === null)
  } finally { cleanup(); globalThis.fetch = original }
})

test('scenes without example references never request even the catalog', async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { ExampleDownloads } = await import('../src/features/scene3d/ExampleDownloads')
  globalThis.fetch = (() => { assert.fail('unexpected request') }) as typeof fetch
  try { const { container } = render(<ExampleDownloads required={[]} />); assert.equal(container.textContent, '') }
  finally { cleanup(); globalThis.fetch = original }
})
