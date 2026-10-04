import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useState } from 'react'
import { JSDOM } from 'jsdom'
import type { Scene3DSlot } from '../src/features/scene3d/types.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
    HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement,
    HTMLSelectElement: dom.window.HTMLSelectElement, Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}
installDom()

const hero = (): Scene3DSlot => ({ id: 'hero', slot: 'subject_1', position: [0, 0, 0], rotationY: 0, scale: 1, sourceUrl: 'hero.glb', media: 'model3d', clip: null, character: { id: 'ada', name: 'Ada' } })
const cup = (): Scene3DSlot => ({ id: 'cup', slot: 'prop', position: [1, 0, 0], rotationY: 0, scale: 1, sourceUrl: 'cup.glb', media: 'model3d', clip: null })

test('the slot panel parents a prop to the right hand and can let it go', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DHoldControls } = await import('../src/features/scene3d/Scene3DHoldControls.tsx')
  function Harness() {
    const [prop, setProp] = useState(cup)
    return <Scene3DHoldControls slot={prop} slots={[hero(), prop]} disabled={false} onChange={patch => setProp(current => ({ ...current, ...patch }))} />
  }
  try {
    render(<Harness />)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hold in the hand' }))
    assert.equal((screen.getByRole('combobox', { name: 'Hand cup' }) as HTMLSelectElement).value, 'right')
    assert.equal((screen.getByRole('combobox', { name: 'Character cup' }) as HTMLSelectElement).value, 'hero')
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Offset Y cup' }), { target: { value: '0.05' } })
    assert.equal((screen.getByRole('spinbutton', { name: 'Offset Y cup' }) as HTMLInputElement).value, '0.05')
    fireEvent.click(screen.getByRole('checkbox', { name: 'Hold in the hand' }))
    assert.equal(screen.queryByRole('combobox', { name: 'Hand cup' }), null)
  } finally { cleanup() }
})
