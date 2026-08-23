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

function renderDraft() {
  window.localStorage.clear()
  window.localStorage.setItem('maestro-video-editor-draft-v1', JSON.stringify({
    projectName: 'Playhead', resolution: { label: 'Landscape 480p', width: 864, height: 480 }, fps: 30,
    clips: twoClips(),
  }))
}

test('clicking a clip parks the playhead at that clip start', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { VideoEditorPanel } = await import('../src/features/video-editor/VideoEditorPanel.tsx')
  renderDraft()
  const view = render(<VideoEditorPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Select clip 2: Second' }))
  assert.equal((screen.getByLabelText('Playhead seconds') as HTMLInputElement).value, '8.00')
  fireEvent.click(screen.getByRole('button', { name: 'Play' }))
  assert.ok(screen.getByRole('button', { name: 'Pause' }))
  view.unmount()
  cleanup()
})

test('clicking a transition parks the playhead at the join', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { VideoEditorPanel } = await import('../src/features/video-editor/VideoEditorPanel.tsx')
  renderDraft()
  const view = render(<VideoEditorPanel />)
  fireEvent.click(screen.getByRole('button', { name: 'Select transition 1' }))
  assert.equal((screen.getByLabelText('Playhead seconds') as HTMLInputElement).value, '8.00')
  view.unmount()
  cleanup()
})

test('playhead seconds input seeks to an exact time', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { VideoEditorPanel } = await import('../src/features/video-editor/VideoEditorPanel.tsx')
  renderDraft()
  const view = render(<VideoEditorPanel />)
  const seconds = screen.getByLabelText('Playhead seconds') as HTMLInputElement
  fireEvent.change(seconds, { target: { value: '3.25' } })
  fireEvent.blur(seconds)
  assert.equal((screen.getByLabelText('Playhead seconds') as HTMLInputElement).value, '3.25')
  assert.equal(screen.getByTestId('timeline-playhead').getAttribute('aria-valuenow'), '3.25')
  view.unmount()
  cleanup()
})
