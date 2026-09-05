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

test('Video Editor keeps import, export, trim, inspector and timeline reachable in the responsive DOM', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { VideoEditorPanel } = await import('../src/features/video-editor/VideoEditorPanel.tsx')
  dom.window.localStorage.setItem('maestro-video-editor-draft-v1', JSON.stringify({
    projectName: 'Mobile edit', resolution: { label: 'Landscape 480p', width: 864, height: 480 }, fps: 30,
    clips: [{
      id: 'clip-1', name: 'Opening clip', source: 'opening.mp4', previewUrl: 'opening.mp4', thumbnailUrl: '',
      duration: 12, width: 1920, height: 1080, fps: 30, has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
      trimStart: 1, trimEnd: 10, volume: 1, muted: false, fit: 'fit', transition: 'none', transitionDuration: 0.5,
      transitionText: 'Momentos después…', transitionTextSize: 100,
    }],
  }))

  const view = render(<VideoEditorPanel />)
  const root = screen.getByTestId('video-editor-panel')
  const toolbar = screen.getByRole('toolbar', { name: 'Video editor tools' })
  const inspector = screen.getByRole('complementary', { name: 'Video editor inspector' })
  const timeline = screen.getByRole('region', { name: 'Video editor timeline' })

  assert.match(root.className, /min-h-0/)
  assert.match(toolbar.className, /flex-wrap/)
  assert.ok(screen.getByRole('button', { name: 'Import' }))
  assert.ok(screen.getByRole('button', { name: 'Export MP4' }))
  assert.ok(screen.getByLabelText('Exact in'))
  assert.ok(screen.getByLabelText('Exact out'))
  assert.match(inspector.className, /overflow-y-auto/)
  assert.match(timeline.className, /h-40/)
  assert.ok(screen.getByLabelText('Timeline playhead'))
  assert.ok(screen.getByRole('button', { name: 'Split' }))
  assert.ok(screen.getByText(/Timeline · 1 clip/))
  view.unmount()
  cleanup()
})
