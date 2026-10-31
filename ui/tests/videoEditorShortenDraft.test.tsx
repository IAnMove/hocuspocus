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
  const raf = () => 1
  const caf = () => {}
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    HTMLSelectElement: dom.window.HTMLSelectElement,
    HTMLMediaElement: dom.window.HTMLMediaElement,
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: ResizeObserverStub,
    requestAnimationFrame: raf,
    cancelAnimationFrame: caf,
  })
  Object.assign(dom.window, {
    requestAnimationFrame: raf,
    cancelAnimationFrame: caf,
  })
  Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'play', {
    configurable: true,
    value: () => Promise.resolve(),
  })
  Object.defineProperty(dom.window.HTMLMediaElement.prototype, 'pause', {
    configurable: true,
    value() {},
  })
  Object.defineProperty(dom.window, 'ResizeObserver', { configurable: true, value: ResizeObserverStub })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  return dom
}

const dom = installDom()

function clip() {
  return {
    id: 'clip-open', name: 'Opening', source: 'opening.mp4', previewUrl: 'opening.mp4', thumbnailUrl: '',
    duration: 12, width: 1920, height: 1080, fps: 30, has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
    trimStart: 0, trimEnd: 10, volume: 1, muted: false, fit: 'fit', transition: 'none', transitionDuration: 0.5,
    transitionText: '', transitionTextSize: 100,
  }
}

function soundtrack(source = '/outputs/score.mp3') {
  return {
    name: 'score.mp3', source, duration: 240, trimStart: 0, trimEnd: 240, volume: 1, loop: false,
  }
}

test('Shorten song persists the new soundtrack so a later clip draft does not restore the full song', {
  concurrency: false,
}, async () => {
  const { render, screen, waitFor, cleanup, fireEvent } = await import('@testing-library/react')
  const { VideoEditorPanel } = await import('../src/features/video-editor/VideoEditorPanel.tsx')
  const { loadEditorDraft, persistEditorDraft, videoEditorDraftStorageKey } = await import(
    '../src/features/video-editor/editorDraft.ts'
  )
  const resolution = { label: 'Landscape 480p', width: 864, height: 480 }
  const previousFetch = globalThis.fetch
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/v1/audio/shorten')) {
      const body = JSON.parse(String(init?.body || '{}'))
      if (body.preview) {
        return {
          ok: true,
          json: async () => ({ preview: true, keep: [[0, 60]], time_map: [[0, 0, 0]] }),
        } as Response
      }
      return {
        ok: true,
        json: async () => ({
          file: 'short.mp3',
          url: '/outputs/short.mp3',
          duration: 60,
          keep: [[0, 60]],
          montage: {
            clips: [{ id: 'clip-open', trimStart: 0, trimEnd: 8 }],
            overlays: [],
            audioCues: [],
          },
        }),
      } as Response
    }
    return { ok: true, json: async () => ({}) } as Response
  }) as typeof fetch

  dom.window.localStorage.clear()
  persistEditorDraft([clip()] as never, 'Music video', resolution, 30, 'default', soundtrack())

  let view: { unmount: () => void } | null = null
  try {
    view = render(<VideoEditorPanel />)
    fireEvent.click(screen.getByRole('button', { name: 'Shorten song to 180 s' }))
    const apply = await screen.findByRole('button', { name: 'Apply' })
    fireEvent.click(apply)
    await waitFor(() => {
      assert.match(loadEditorDraft('default').soundtrack?.source || '', /short\.mp3/)
      assert.equal(loadEditorDraft('default').soundtrack?.duration, 60)
      assert.equal(loadEditorDraft('default').clips[0]?.trimEnd, 8)
    })

    persistEditorDraft(
      loadEditorDraft('default').clips,
      'Music video',
      resolution,
      30,
      'default',
    )
    await new Promise(resolve => setTimeout(resolve, 700))
    const kept = loadEditorDraft('default').soundtrack
    assert.match(kept?.source || '', /short\.mp3/, 'a clip-only persist must keep the shortened song')
    assert.equal(kept?.duration, 60)
    assert.ok(dom.window.localStorage.getItem(videoEditorDraftStorageKey('default'))?.includes('short.mp3'))
  } finally {
    view?.unmount()
    cleanup()
    globalThis.fetch = previousFetch
  }
})
