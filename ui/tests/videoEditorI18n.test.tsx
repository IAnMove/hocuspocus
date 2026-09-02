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

test('Video Editor toolbar and empty chrome follow the active language', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { ensureUiI18n, setUiLanguage } = await import('../src/i18n/index.ts')
  const { VideoEditorPanel } = await import('../src/features/video-editor/VideoEditorPanel.tsx')
  ensureUiI18n()
  await setUiLanguage('en')
  dom.window.localStorage.clear()
  let view: { unmount: () => void } | null = null
  try {
    view = render(<VideoEditorPanel />)
    assert.ok(screen.getByRole('button', { name: 'Import' }))
    assert.ok(screen.getByRole('button', { name: 'Export MP4' }))
    assert.ok(screen.getByRole('toolbar', { name: 'Video editor tools' }))
    assert.ok(screen.getByText('Add your first video'))
    await setUiLanguage('es')
    view.unmount()
    view = render(<VideoEditorPanel />)
    assert.ok(screen.getByRole('button', { name: 'Importar' }))
    assert.ok(screen.getByRole('button', { name: 'Exportar MP4' }))
    assert.ok(screen.getByRole('toolbar', { name: 'Herramientas del Video Editor' }))
    assert.ok(screen.getByText('Añade tu primer vídeo'))
  } finally {
    view?.unmount()
    await setUiLanguage('en')
    cleanup()
  }
})
