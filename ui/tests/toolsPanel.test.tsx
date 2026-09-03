import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLImageElement: dom.window.HTMLImageElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class { observe() {} disconnect() {} },
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

test('Tools exposes exact library images for background removal', async () => {
  const { render, screen, waitFor, fireEvent, cleanup } = await import('@testing-library/react')
  const { ToolsPanel } = await import('../src/components/Sidebar/ToolsPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  globalThis.fetch = async input => {
    const requestUrl = typeof input === 'string' ? input : (input as Request).url || String(input)
    if (requestUrl.includes('/api/v1/assets')) {
      return new Response(JSON.stringify({
        total: 1,
        assets: [{
          id: 'asset-hero', kind: 'image', filename: 'hero.png', size_bytes: 12,
          created_at: 1, completed_at: 2, metadata_status: 'canonical', workspace_ids: ['default'],
          locations: [{ workspace_id: 'default', filename: 'hero.png', url: '/api/v1/file/hero.png?workspace=default' }],
          url: '/api/v1/file/hero.png?workspace=default',
          origin: { tool: 'studio' }, execution: {}, model: { provider: 'local', id: 'flux' },
          prompt_preview: 'hero',
        }],
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${requestUrl}`)
  }
  useStore.setState({
    toolsTool: 'remove_background', toolsSourcePath: null, toolsSourceName: null,
    toolsSourceUrl: null, toolsSourceAssetId: null, toolsSourceWorkspace: null, toolsSourceKind: null,
    activeWorkspace: 'default', outputs: [], selectedOutput: -1,
  } as never)
  try {
    render(<ToolsPanel />)
    await waitFor(() => screen.getByRole('option', { name: 'hero.png' }))
    const picker = screen.getByRole('combobox', { name: 'Source Image' })
    assert.ok(screen.getByRole('button', { name: 'Remove background' }))
    assert.ok(screen.getByText('Upload an image'))
    assert.ok(screen.getByRole('option', { name: 'hero.png' }))

    fireEvent.change(picker, { target: { value: 'asset-hero' } })
    assert.equal(useStore.getState().toolsSourceAssetId, 'asset-hero')
    assert.equal(useStore.getState().toolsSourcePath, 'hero.png')
    assert.equal(useStore.getState().toolsSourceKind, 'image')
    assert.equal(useStore.getState().toolsSourceWorkspace, 'default')
    assert.ok(screen.getByRole('img', { name: 'hero.png' }))
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
  }
})
