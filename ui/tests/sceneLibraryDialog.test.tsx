import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

// tsx's Node test transform uses the classic JSX factory for nested UI files.
// Vite uses the automatic runtime in production, so expose the factory only here.
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

test('the 3D Video library dialog paginates saved scenes and opens a previewed project', { concurrency: false }, async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { SceneLibraryDialog } = await import('../src/components/Sidebar/SceneLibraryDialog.tsx')
  const originalFetch = globalThis.fetch
  const scenes = Array.from({ length: 9 }, (_, index) => ({
    name: `2026-08-25-22h21m0${index}s_Station-loop-${index}_aaaaaa.scene.json`,
    type: 'scene',
    mode: null,
    size: 12,
    created_at: 1000 + index,
    url: `/api/v1/file/scene-${index}.scene.json`,
    thumbnail_url: `/api/v1/file/scene-${index}.scene.preview.png`,
  }))
  const sampleScene = {
    version: 1,
    name: 'Station loop 0',
    width: 1280,
    height: 720,
    duration: 10,
    layers: [{
      id: 'plate', name: 'Plate', type: 'image', source: '/api/v1/file/plate.jpg', visible: true, z: 0,
      transform: { x: 50, y: 50, scale: 1, opacity: 1 },
      animation: { start: { x: 50, y: 50, scale: 1 }, end: { x: 50, y: 50, scale: 1 }, duration: 10, curve: 'linear' },
    }],
  }
  globalThis.fetch = (async (input: string | URL | Request) => {
    const url = String(input)
    if (url.includes('/api/v1/outputs') && url.includes('media_type=scene')) {
      const parsed = new URL(url, 'http://localhost')
      const offset = Number(parsed.searchParams.get('offset') || 0)
      return new Response(JSON.stringify({ outputs: scenes.slice(offset, offset + 8), total: scenes.length }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.includes('/api/v1/file/scene-0.scene.json')) {
      return new Response(JSON.stringify(sampleScene), { headers: { 'content-type': 'application/json' } })
    }
    throw new Error(`Unexpected request: ${url}`)
  }) as typeof fetch
  const opened: string[] = []
  try {
    render(<SceneLibraryDialog open workspace="default" onClose={() => undefined} onPickFile={() => undefined} onOpenScene={scene => opened.push(scene.name)} />)
    await waitFor(() => assert.ok(screen.getAllByText('Station loop 0').length >= 1))
    assert.match(screen.getByText(/saved · page/).textContent || '', /9 saved · page 1 \/ 2/)
    fireEvent.click(screen.getByLabelText('Next page'))
    await waitFor(() => assert.ok(screen.getAllByText('Station loop 8').length >= 1))
    fireEvent.click(screen.getByLabelText('Previous page'))
    await waitFor(() => assert.ok(screen.getAllByText('Station loop 0').length >= 1))
    fireEvent.click(screen.getByRole('button', { name: 'Open in 3D Video' }))
    await waitFor(() => assert.deepEqual(opened, ['Station loop 0']))
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
  }
})
