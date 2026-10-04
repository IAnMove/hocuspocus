import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import { createUserTemplate } from '../src/features/scene3d/userTemplates.ts'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement,
  File: dom.window.File, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  HTMLCanvasElement: dom.window.HTMLCanvasElement, ResizeObserver: class { observe() {} disconnect() {} },
  getComputedStyle: dom.window.getComputedStyle,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test.afterEach(() => { window.localStorage.clear() })

function jsonFile(name: string, value: unknown) {
  const body = JSON.stringify(value)
  const file = new File([body], name, { type: 'application/json' })
  Object.defineProperty(file, 'text', { value: async () => body })
  return file
}

test('opening a scenario template as shot JSON points to My scenarios', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { Scene3DDocumentControls } = await import('../src/features/scene3d/Scene3DDocumentControls')
  const pack = createUserTemplate({ document: createDefaultScene3DDocument(), title: 'Dock', id: 'user-dock' })
  let loaded = 0
  try {
    render(<Scene3DDocumentControls document={createDefaultScene3DDocument()} disabled={false} workspace="demo"
      preview={() => undefined} onChange={() => {}} onLoad={() => { loaded++ }} />)
    fireEvent.change(screen.getByLabelText('Open shot JSON'), {
      target: { files: [jsonFile('dock.world3d.template.json', pack)] },
    })
    await waitFor(() => assert.match(screen.getByRole('alert').textContent || '', /My templates/))
    assert.equal(loaded, 0)
  } finally { cleanup() }
})
