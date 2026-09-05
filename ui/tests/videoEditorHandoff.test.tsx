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

function clip(name: string) {
  return {
    id: `existing-${name}`, name, source: `${name}.mp4`, previewUrl: `${name}.mp4`, thumbnailUrl: '',
    duration: 10, width: 1920, height: 1080, fps: 30, has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
    trimStart: 0, trimEnd: 10, volume: 1, muted: false, fit: 'fit', transition: 'none', transitionDuration: 0.5,
    transitionText: 'Momentos después…', transitionTextSize: 100,
  }
}

test('Series handoff validates all sources before replacing the draft and can retry', { concurrency: false }, async () => {
  const { render, screen, waitFor, cleanup, fireEvent } = await import('@testing-library/react')
  const { setUiLanguage } = await import('../src/i18n/index.ts')
  const { VideoEditorPanel } = await import('../src/features/video-editor/VideoEditorPanel.tsx')
  const { videoEditorDraftStorageKey } = await import('../src/features/video-editor/editorDraft.ts')
  const draftKey = videoEditorDraftStorageKey('default')
  let failSecond = true
  const probed: string[] = []
  globalThis.fetch = (async (_input: string | URL | Request, init?: RequestInit) => {
    const source = JSON.parse(String(init?.body || '{}')).source as string
    probed.push(source)
    if (source === 'second.mp4' && failSecond) {
      return { ok: false, json: async () => ({ detail: 'invalid source' }) } as Response
    }
    return {
      ok: true,
      json: async () => ({
        duration: 10, width: 1920, height: 1080, fps: 30,
        has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
      }),
    } as Response
  }) as typeof fetch
  dom.window.confirm = () => true
  const oldDraft = {
    projectName: 'Existing montage', resolution: { label: 'Landscape 480p', width: 864, height: 480 }, fps: 30,
    clips: [clip('old')],
  }
  const handoff = {
    projectName: 'Series handoff',
    resolution: { label: 'Landscape 720p', width: 1280, height: 720 },
    clips: [{ name: 'First', url: 'first.mp4' }, { name: 'Second', url: 'second.mp4' }, { name: 'Third', url: 'third.mp4' }],
  }
  dom.window.localStorage.setItem('maestro-video-editor-draft-v1', JSON.stringify(oldDraft))
  dom.window.localStorage.setItem('maestro-video-editor-pending-sequence', JSON.stringify(handoff))

  const view = render(<VideoEditorPanel />)
  await screen.findByRole('button', { name: 'Retry hand-off' })
  assert.deepEqual(probed, ['first.mp4', 'second.mp4'])
  assert.deepEqual(
    JSON.parse(dom.window.localStorage.getItem(draftKey) || '{}').clips.map((item: { name: string }) => item.name),
    ['old'],
  )
  assert.deepEqual(JSON.parse(dom.window.localStorage.getItem('maestro-video-editor-pending-sequence') || '{}'), handoff)
  assert.match(screen.getByText(/current draft were kept/).textContent || '', /current draft were kept/)

  await setUiLanguage('es')
  await screen.findByRole('button', { name: 'Reintentar la entrega' })
  assert.deepEqual(probed, ['first.mp4', 'second.mp4'])
  await setUiLanguage('en')
  await screen.findByRole('button', { name: 'Retry hand-off' })
  assert.deepEqual(probed, ['first.mp4', 'second.mp4'])

  failSecond = false
  fireEvent.click(screen.getByRole('button', { name: 'Retry hand-off' }))
  await waitFor(() => {
    assert.match(screen.getByText(/Timeline · 3 clips/).textContent || '', /Timeline · 3 clips/)
    assert.deepEqual(
      JSON.parse(dom.window.localStorage.getItem(draftKey) || '{}').clips.map((item: { name: string }) => item.name),
      ['First', 'Second', 'Third'],
    )
  })
  assert.equal(dom.window.localStorage.getItem('maestro-video-editor-pending-sequence'), null)
  assert.deepEqual(probed, ['first.mp4', 'second.mp4', 'first.mp4', 'second.mp4', 'third.mp4'])
  view.unmount()
  cleanup()
})
