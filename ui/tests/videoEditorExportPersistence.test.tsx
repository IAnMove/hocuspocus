import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  class ResizeObserverStub {
    observe() {}
    disconnect() {}
  }
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLMediaElement: dom.window.HTMLMediaElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: ResizeObserverStub,
  })
  Object.defineProperty(dom.window, 'ResizeObserver', { configurable: true, value: ResizeObserverStub })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  return dom
}

const dom = installDom()

test('Video Editor persists one export per workspace and reconnects after remount', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup, fireEvent } = await import('@testing-library/react')
  const { setUiLanguage } = await import('../src/i18n/index.ts')
  const { VideoEditorPanel } = await import('../src/features/video-editor/VideoEditorPanel.tsx')
  dom.window.localStorage.clear()
  dom.window.localStorage.setItem('maestro-video-editor-draft-v1', JSON.stringify({
    projectName: 'Persistent export',
    resolution: { label: 'Landscape 480p', width: 864, height: 480 },
    fps: 30,
    clips: [{
      id: 'clip-1', name: 'Opening clip', source: 'opening.mp4', previewUrl: 'opening.mp4', thumbnailUrl: '',
      duration: 12, width: 1920, height: 1080, fps: 30, has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
      trimStart: 1, trimEnd: 10, volume: 1, muted: false, fit: 'fit', transition: 'none', transitionDuration: 0.5,
      transitionText: 'Momentos después…', transitionTextSize: 100,
    }],
  }))

  const jobId = 'export-persistent-42'
  let postCount = 0
  let statusCount = 0
  let releaseFirstStatus: (() => void) | null = null
  const firstStatusPending = new Promise<void>(resolve => {
    releaseFirstStatus = resolve
  })
  const previousFetch = globalThis.fetch
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    if (url.endsWith('/api/v1/video-editor/export') && init?.method === 'POST') {
      postCount += 1
      return {
        ok: true,
        json: async () => ({
          job_id: jobId, status: 'queued', progress: 0, message: 'Queued',
          filename: null, url: null, error: null,
        }),
      } as Response
    }
    if (url.includes(`/api/v1/video-editor/export/${jobId}`)) {
      statusCount += 1
      if (statusCount === 1) await firstStatusPending
      return {
        ok: true,
        json: async () => ({
          job_id: jobId, status: 'running', progress: Math.min(90, statusCount * 10), message: 'Rendering',
          filename: null, url: null, error: null,
        }),
      } as Response
    }
    throw new Error(`Unexpected request: ${url}`)
  }) as typeof fetch

  let first: { unmount: () => void } | null = null
  let second: { unmount: () => void } | null = null
  try {
    first = render(<VideoEditorPanel />)
    fireEvent.click(screen.getByRole('button', { name: 'Export MP4' }))
    await waitFor(() => assert.equal(postCount, 1))
    await waitFor(() => assert.ok(statusCount >= 1))
    assert.equal(dom.window.localStorage.getItem('maestro-video-editor-export-v1:default'), jobId)
    await setUiLanguage('es')
    await screen.findByRole('button', { name: 'Exportar MP4' })
    assert.equal(statusCount, 1)
    releaseFirstStatus?.()
    await screen.findByText('Rendering')
    first.unmount()
    first = null

    const statusCountBeforeRemount = statusCount
    second = render(<VideoEditorPanel />)
    await waitFor(() => assert.ok(statusCount > statusCountBeforeRemount))
    assert.equal(postCount, 1)
    assert.match((await screen.findByText('Rendering')).textContent || '', /Rendering/)
  } finally {
    first?.unmount()
    second?.unmount()
    cleanup()
    await setUiLanguage('en')
    globalThis.fetch = previousFetch
  }
})
