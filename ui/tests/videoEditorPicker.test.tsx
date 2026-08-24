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
    MouseEvent: dom.window.MouseEvent,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: ResizeObserverStub,
  })
  Object.defineProperty(dom.window, 'ResizeObserver', { configurable: true, value: ResizeObserverStub })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
  return dom
}

const dom = installDom()

function videoOutput(name: string) {
  return {
    name,
    type: 'video',
    mode: 'video',
    url: `/api/v1/file/${name}?workspace=default`,
    thumbnail_url: `/api/v1/outputs/thumbnail/${name}?workspace=default`,
    size: 12,
    created_at: 1,
    completed_at: 1,
    favorite: false,
  }
}

test('editorSourcePath strips workspace query from gallery file URLs', async () => {
  const { editorSourcePath } = await import('../src/features/video-editor/editorHandoff.ts')
  assert.equal(
    editorSourcePath('/api/v1/file/minimax_h3_713afac9.mp4?workspace=default'),
    'minimax_h3_713afac9.mp4',
  )
  assert.equal(editorSourcePath('minimax_h3_713afac9.mp4?workspace=default'), 'minimax_h3_713afac9.mp4')
  assert.equal(editorSourcePath('opening.mp4'), 'opening.mp4')
})

test('Video Editor picker keeps multiple HocusPocus videos selected until Add', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup, fireEvent } = await import('@testing-library/react')
  const { VideoEditorPanel } = await import('../src/features/video-editor/VideoEditorPanel.tsx')
  dom.window.localStorage.clear()
  const probed: Array<{ source: string; workspace?: string }> = []
  globalThis.fetch = (async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(input)
    if (url.includes('/api/v1/outputs')) {
      return {
        ok: true,
        json: async () => ({
          outputs: [videoOutput('minimax_h3_713afac9.mp4'), videoOutput('second_clip.mp4')],
          total: 2,
        }),
      } as Response
    }
    if (url.includes('/api/v1/video-editor/probe')) {
      const body = JSON.parse(String(init?.body || '{}')) as { source: string; workspace?: string }
      probed.push(body)
      return {
        ok: true,
        json: async () => ({
          duration: 8, width: 1280, height: 720, fps: 24,
          has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
        }),
      } as Response
    }
    throw new Error(`Unexpected request: ${url}`)
  }) as typeof fetch

  const view = render(<VideoEditorPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'From HocusPocus' }))
  await screen.findByRole('listbox', { name: 'HocusPocus videos' })
  fireEvent.click(screen.getByRole('option', { name: 'minimax_h3_713afac9.mp4' }))
  fireEvent.click(screen.getByRole('option', { name: 'second_clip.mp4' }))
  assert.equal(screen.getByRole('option', { name: 'minimax_h3_713afac9.mp4' }).getAttribute('aria-selected'), 'true')
  assert.equal(screen.getByRole('option', { name: 'second_clip.mp4' }).getAttribute('aria-selected'), 'true')
  fireEvent.click(screen.getByRole('button', { name: 'Add 2 videos' }))
  await waitFor(() => assert.match(screen.getByText(/Timeline · 2 clips/).textContent || '', /Timeline · 2 clips/))
  assert.equal(probed.length, 2)
  assert.equal(probed[0].source, 'minimax_h3_713afac9.mp4')
  assert.equal(probed[0].workspace, 'default')
  assert.equal(probed[1].source, 'second_clip.mp4')
  view.unmount()
  cleanup()
})
