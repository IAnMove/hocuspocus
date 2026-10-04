import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useState } from 'react'
import { JSDOM } from 'jsdom'
import type { Scene3DClipCatalogEntry, Scene3DSlot } from '../src/features/scene3d/types.ts'

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

const catalog: Scene3DClipCatalogEntry[] = [
  { index: 0, name: 'Walk', durationSeconds: 1.2 },
  { index: 1, name: 'Wave', durationSeconds: 0.8 },
]
const base = (): Scene3DSlot => ({
  id: 'subject_1', slot: 'subject_1', position: [0, 0, 0], rotationY: 0, scale: 1,
  sourceUrl: '/api/v1/file/hero.glb?workspace=one', media: 'model3d',
  clip: { index: 0, name: 'Walk' }, clipPlayback: { speed: 1, start: 0, loop: true },
})

test('the editor builds a sequence, fades the next clip, and can return to one clip', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DAnimationControls } = await import('../src/features/scene3d/Scene3DAnimationControls.tsx')
  function Harness() {
    const [slot, setSlot] = useState(base)
    return <Scene3DAnimationControls slot={slot} clips={catalog} duration={8} disabled={false}
      onChange={patch => setSlot(current => ({ ...current, ...patch }))} />
  }
  try {
    render(<Harness />)
    assert.equal(screen.queryByText('Several clips with fades. While a sequence is set, the character follows these clips.'), null)
    fireEvent.click(screen.getByRole('button', { name: 'Create sequence' }))
    assert.ok(screen.getByText('Several clips with fades. While a sequence is set, the character follows these clips.'))
    assert.equal(screen.queryByRole('button', { name: 'Fit animation to shot' }), null)
    fireEvent.click(screen.getByRole('button', { name: 'Add clip' }))
    const fades = screen.getAllByRole('spinbutton', { name: 'Fade (s) subject_1' })
    assert.equal((fades[1] as HTMLInputElement).value, '0.3')
    fireEvent.change(fades[1], { target: { value: '0' } })
    assert.equal((screen.getAllByRole('spinbutton', { name: 'Fade (s) subject_1' })[1] as HTMLInputElement).value, '0')
    fireEvent.click(screen.getByRole('button', { name: 'Use one clip' }))
    assert.ok(screen.getByRole('combobox', { name: 'GLB animation subject_1' }))
    assert.equal(screen.queryByRole('button', { name: 'Add clip' }), null)
  } finally { cleanup() }
})
