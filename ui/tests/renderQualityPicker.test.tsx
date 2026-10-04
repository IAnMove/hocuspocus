import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}
installDom()

test('the picker shows a draft estimate and reports final with the shutter', async () => {
  const { render, fireEvent, cleanup } = await import('@testing-library/react')
  const { RenderQualityPicker } = await import('../src/features/render/RenderQualityPicker.tsx')
  const seen: { level: string; shutter: number }[] = []
  try {
    const view = render(<RenderQualityPicker width={1920} height={1080} fps={24} duration={1} onChange={choice => seen.push(choice)} />)
    const estimate = view.getByTestId('render-estimate').textContent ?? ''
    assert.match(estimate, /About/)
    assert.match(estimate, /does not start the render/)
    assert.equal((view.getByTestId('render-shutter') as HTMLInputElement).disabled, true)
    fireEvent.change(view.getByTestId('render-level'), { target: { value: 'final' } })
    fireEvent.change(view.getByTestId('render-shutter'), { target: { value: '90' } })
    assert.deepEqual(seen.at(-1), { level: 'final', shutter: 90 })
    assert.equal((view.getByTestId('render-shutter') as HTMLInputElement).disabled, false)
  } finally { cleanup() }
})
