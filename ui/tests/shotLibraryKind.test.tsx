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
    KeyboardEvent: dom.window.KeyboardEvent,
    MouseEvent: dom.window.MouseEvent,
    MutationObserver: dom.window.MutationObserver,
    ResizeObserver: class { observe() {} disconnect() {} },
    getComputedStyle: dom.window.getComputedStyle,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}
installDom()

test.afterEach(() => { window.localStorage.clear() })

async function openLibrary() {
  const { render } = await import('@testing-library/react')
  const { Scene3DShotLibraryDialog } = await import('../src/features/scene3d/Scene3DShotLibrary')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates')
  render(<Scene3DShotLibraryDialog document={applyScene3DTemplate('two-shot')} applyDisabled={false} editingLocked={false} keepAssets onKeepAssets={() => {}}
    onTemplate={() => {}} onUserTemplate={() => {}} onClose={() => {}} />)
}

test('the kind chips split the cinema shelf into looks, camera techniques and scenes, and reset with the shot type', async () => {
  const { screen, fireEvent, cleanup, within } = await import('@testing-library/react')
  try {
    await openLibrary()
    fireEvent.click(screen.getByRole('button', { name: 'Cinema' }))
    const chips = screen.getByRole('group', { name: 'Kind' })
    assert.deepEqual(within(chips).getAllByRole('button').map(button => button.textContent), ['Any kind', 'Scenes', 'Camera', 'Looks', 'Transitions'])
    assert.ok(screen.getByTestId('world3d-template-cine-noir') && screen.getByTestId('world3d-template-cine-dolly-in'))
    fireEvent.click(within(chips).getByRole('button', { name: 'Looks' }))
    assert.ok(screen.getByTestId('world3d-template-cine-noir'))
    assert.equal(screen.queryByTestId('world3d-template-cine-dolly-in'), null)
    assert.equal(screen.queryByTestId('world3d-template-dance-orbit'), null)
    fireEvent.click(within(chips).getByRole('button', { name: 'Camera' }))
    assert.ok(screen.getByTestId('world3d-template-cine-dolly-in'))
    assert.equal(screen.queryByTestId('world3d-template-cine-noir'), null)
    fireEvent.click(screen.getByRole('button', { name: 'Action' }))
    assert.equal(screen.getByRole('group', { name: 'Kind' }).querySelector('[aria-pressed="true"]')?.textContent, 'Any kind', 'a new shot type starts on every shelf')
    assert.ok(screen.getByTestId('world3d-template-car-chase'))
    fireEvent.click(screen.getByRole('button', { name: 'Sea' }))
    assert.equal(screen.queryByRole('group', { name: 'Kind' }), null, 'one shelf needs no chips')
  } finally {
    cleanup()
  }
})
