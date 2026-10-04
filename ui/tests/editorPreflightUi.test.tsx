import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { EditorClip } from '../src/features/video-editor/editorClipNormalization.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}
installDom()

function clip(patch: Partial<EditorClip> = {}): EditorClip {
  return {
    id: 'a', name: 'a', source: 'a.mp4', previewUrl: '', thumbnailUrl: '',
    trimStart: 0, trimEnd: 4, volume: 1, muted: false, fit: 'fit',
    transition: 'none', transitionDuration: 0, transitionText: '', transitionTextSize: 32,
    duration: 4, width: 1280, height: 720, fps: 30, has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
    ...patch,
  }
}

test('the editor shows a gap warning and does not offer a block', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { EditorPreflightNotices } = await import('../src/features/video-editor/EditorPreflightNotices.tsx')
  try {
    const { rerender } = render(<EditorPreflightNotices clips={[clip()]} soundtrack={null} />)
    assert.equal(screen.queryByTestId('editor-preflight'), null)
    rerender(<EditorPreflightNotices clips={[]} soundtrack={null} />)
    assert.match(screen.getByTestId('editor-preflight').textContent ?? '', /do not block export/)
    assert.match(screen.getByTestId('editor-preflight').textContent ?? '', /Gap from 0.00 s/)
  } finally { cleanup() }
})
