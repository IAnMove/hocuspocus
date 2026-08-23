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
    HTMLSelectElement: dom.window.HTMLSelectElement,
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

function twoClips() {
  return [
    {
      id: 'clip-a', name: 'First', source: 'first.mp4', previewUrl: 'first.mp4', thumbnailUrl: '',
      duration: 10, width: 1280, height: 720, fps: 24, has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
      trimStart: 0, trimEnd: 8, volume: 1, muted: false, fit: 'fit', transition: 'none', transitionDuration: 0.5,
      transitionText: 'Momentos después…', transitionTextSize: 100,
    },
    {
      id: 'clip-b', name: 'Second', source: 'second.mp4', previewUrl: 'second.mp4', thumbnailUrl: '',
      duration: 10, width: 1280, height: 720, fps: 24, has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
      trimStart: 0, trimEnd: 6, volume: 1, muted: false, fit: 'fit', transition: 'none', transitionDuration: 0.5,
      transitionText: 'Momentos después…', transitionTextSize: 100,
    },
  ]
}

test('Video Editor can apply one transition to every gap', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { VideoEditorPanel } = await import('../src/features/video-editor/VideoEditorPanel.tsx')
  dom.window.localStorage.clear()
  dom.window.localStorage.setItem('maestro-video-editor-draft-v1', JSON.stringify({
    projectName: 'Gaps', resolution: { label: 'Landscape 480p', width: 864, height: 480 }, fps: 30,
    clips: twoClips(),
  }))
  const view = render(<VideoEditorPanel />)
  fireEvent.change(screen.getByLabelText('Default transition for all gaps'), { target: { value: 'crossfade' } })
  fireEvent.click(screen.getByRole('button', { name: 'Apply to all' }))
  assert.match(screen.getByTitle(/Transition: Crossfade/).textContent || '', /Crossfade/)
  view.unmount()
  cleanup()
})
