import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    React,
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    HTMLCanvasElement: dom.window.HTMLCanvasElement,
    HTMLButtonElement: dom.window.HTMLButtonElement,
    HTMLInputElement: dom.window.HTMLInputElement,
    Event: dom.window.Event,
    MouseEvent: dom.window.MouseEvent,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class { observe() {} disconnect() {} },
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}
installDom()

test('the shot library filters by Action and by set without dumping every card', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DTemplateBrowser } = await import('../src/features/scene3d/Scene3DTemplateBrowser')
  const picks: string[] = []
  try {
    render(<Scene3DTemplateBrowser disabled={false} onSelect={id => picks.push(id)} />)
    assert.ok(screen.getByRole('group', { name: 'Shot type' }))
    fireEvent.click(screen.getByRole('button', { name: 'Action' }))
    assert.ok(screen.getByTestId('world3d-template-sea-deck'))
    assert.ok(screen.getByTestId('world3d-template-jungle-ambush'))
    assert.equal(screen.queryByTestId('world3d-template-two-shot'), null)
    fireEvent.click(screen.getByRole('button', { name: 'Sea' }))
    assert.ok(screen.getByTestId('world3d-template-sea-deck'))
    assert.equal(screen.queryByTestId('world3d-template-jungle-ambush'), null)
    fireEvent.click(screen.getByTestId('world3d-template-sea-deck'))
    assert.deepEqual(picks, ['sea-deck'])
  } finally {
    cleanup()
  }
})
