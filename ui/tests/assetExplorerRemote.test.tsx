import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { ASSET_PICKER_PAGE_SIZE } from '../src/features/asset-picker/types.ts'

Object.assign(globalThis, { React })

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLImageElement: dom.window.HTMLImageElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

function catalogAsset(index: number, filename = `hit-${index}.png`) {
  return {
    id: `asset-${index}`,
    kind: 'image',
    filename,
    size_bytes: 12,
    created_at: 1_700_000_000 + index,
    completed_at: 1_700_000_100 + index,
    metadata_status: 'canonical',
    workspace_ids: ['film'],
    locations: [{ workspace_id: 'film', filename, url: `/api/v1/file/${filename}?workspace=film` }],
    url: `/api/v1/file/${filename}?workspace=film`,
    origin: { tool: 'studio' },
    execution: {},
    model: {},
    prompt_preview: '',
  }
}

test('remote explorer pages the catalog by the picker page size and can find a hit past the first 100', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  const all = Array.from({ length: 120 }, (_, index) => catalogAsset(index, index === 110 ? 'wanted.png' : `hit-${index}.png`))
  const calls: URL[] = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost')
    calls.push(url)
    const offset = Number(url.searchParams.get('offset') || '0')
    const limit = Number(url.searchParams.get('limit') || String(ASSET_PICKER_PAGE_SIZE))
    const search = url.searchParams.get('search') || ''
    const pool = search ? all.filter(item => item.filename.includes(search)) : all
    return new Response(JSON.stringify({
      total: pool.length,
      assets: pool.slice(offset, offset + limit),
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  const chosen: string[] = []
  try {
    render(
      <AssetExplorerDialog
        open
        remote
        workspaceId="film"
        title="Library"
        items={[]}
        onClose={() => undefined}
        onChoose={item => { if (item) chosen.push(item.asset_id || item.name) }}
      />,
    )
    await waitFor(() => assert.ok(screen.getByTitle('hit-0.png')))
    assert.equal(calls[0].searchParams.get('limit'), String(ASSET_PICKER_PAGE_SIZE))
    assert.equal(calls[0].searchParams.get('offset'), '0')
    assert.equal(calls[0].searchParams.get('workspace'), 'film')
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    await waitFor(() => assert.ok(calls.some(url => url.searchParams.get('offset') === String(ASSET_PICKER_PAGE_SIZE))))
    fireEvent.change(screen.getByPlaceholderText('Search by name'), { target: { value: 'wanted' } })
    await waitFor(() => assert.ok(calls.some(url => url.searchParams.get('search') === 'wanted')))
    await waitFor(() => assert.ok(screen.getByTitle('wanted.png')))
    fireEvent.click(screen.getByTitle('wanted.png'))
    fireEvent.click(screen.getByRole('button', { name: 'Choose' }))
    assert.deepEqual(chosen, ['asset-110'])
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})

test('remote explorer does not refetch when the parent rebuilds the same constraints object', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup } = await import('@testing-library/react')
  const { AssetExplorerDialog } = await import('../src/components/common/AssetExplorerDialog.tsx')
  const calls: string[] = []
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    calls.push(String(input))
    return new Response(JSON.stringify({
      total: 1,
      assets: [catalogAsset(0, 'clip.mp4')],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  try {
    const view = render(
      <AssetExplorerDialog
        open
        remote
        workspaceId="film"
        title="Library"
        items={[]}
        constraints={{ kinds: ['video'], maxCount: 1, optional: false }}
        onClose={() => undefined}
        onChoose={() => undefined}
      />,
    )
    await waitFor(() => assert.ok(screen.getByTitle('clip.mp4')))
    assert.equal(calls.length, 1)
    view.rerender(
      <AssetExplorerDialog
        open
        remote
        workspaceId="film"
        title="Library"
        items={[]}
        constraints={{ kinds: ['video'], maxCount: 1, optional: false }}
        onClose={() => undefined}
        onChoose={() => undefined}
      />,
    )
    await waitFor(() => assert.ok(screen.getByTitle('clip.mp4')))
    assert.equal(calls.length, 1)
  } finally {
    globalThis.fetch = originalFetch
    cleanup()
  }
})
