import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document.ts'
import type { Scene3DDocument } from '../src/features/scene3d/types.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    HTMLSelectElement: dom.window.HTMLSelectElement, Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver, HTMLInputElement: dom.window.HTMLInputElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}
installDom()

test('the frame size control asks for 4K and portrait keeps that tier', async () => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DDocumentControls } = await import('../src/features/scene3d/Scene3DDocumentControls')
  const seen: Scene3DDocument[] = []
  const document = createDefaultScene3DDocument()
  try {
    const props = { disabled: false, workspace: 'demo', preview: () => undefined, onChange: (next: Scene3DDocument) => seen.push(next), onLoad: () => {} }
    const view = render(<Scene3DDocumentControls document={document} {...props} />)
    const tier = view.getByTestId('world3d-frame-tier') as HTMLSelectElement
    assert.equal(tier.value, 'hd')
    assert.equal(document.width, 1280)
    assert.equal(document.height, 720)
    fireEvent.change(tier, { target: { value: 'uhd' } })
    const uhd = seen.at(-1)
    assert.equal(uhd?.width, 3840)
    assert.equal(uhd?.height, 2160)
    view.rerender(<Scene3DDocumentControls document={uhd!} {...props} />)
    assert.equal((view.getByTestId('world3d-frame-tier') as HTMLSelectElement).value, 'uhd')
    fireEvent.change(view.getByTestId('world3d-frame-format'), { target: { value: 'portrait' } })
    assert.equal(seen.at(-1)?.width, 2160)
    assert.equal(seen.at(-1)?.height, 3840)
  } finally { cleanup() }
})
