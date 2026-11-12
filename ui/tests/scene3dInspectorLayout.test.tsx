import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { Scene3DSlot } from '../src/features/scene3d/types'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React,
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  HTMLSelectElement: dom.window.HTMLSelectElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const slot = (): Scene3DSlot => ({
  id: 'subject_1',
  slot: 'subject_1',
  position: [-12.345, 0.5, 3],
  rotationY: 0,
  rotationX: 0.1,
  rotationZ: -0.2,
  scale: 1.5,
  sourceUrl: 'hero.glb',
  media: 'model3d',
  clip: null,
  character: { id: 'ada', name: 'Ada' },
})

test('position, size and rotation each use a full-width row', async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { Scene3DTransformPanel } = await import('../src/features/scene3d/Scene3DTransformPanel')
  try {
    render(<Scene3DTransformPanel slot={slot()} mode="translate" disabled={false} showModes={false} onMode={() => undefined} onChange={() => undefined} onReset={() => undefined} />)
    const position = screen.getByTestId('scene3d-position-fields')
    const rotation = screen.getByTestId('scene3d-rotation-fields')
    const size = screen.getByTestId('scene3d-size-field')
    assert.match(position.className, /grid-cols-3/)
    assert.match(rotation.className, /grid-cols-3/)
    assert.equal(position.className.includes('grid-cols-2'), false)
    assert.equal(size.className.includes('grid-cols-2'), false)
    assert.equal(size.querySelectorAll('input').length, 1)
    assert.equal((screen.getByLabelText('Position (m) X') as HTMLInputElement).value, '-12.345')
    assert.equal((screen.getByLabelText('Size', { exact: true }) as HTMLInputElement).value, '1.5')
    assert.equal((screen.getByLabelText('Rotation Y (°)', { exact: true }) as HTMLInputElement).value, '0')
    assert.match((screen.getByLabelText('Position (m) X') as HTMLInputElement).className, /w-full/)
  } finally {
    cleanup()
  }
})

test('voice and lip-sync is a collapsible section', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DSpeechSelector } = await import('../src/features/scene3d/speech/Scene3DSpeechSelector')
  let open = false
  try {
    const view = render(<Scene3DSpeechSelector slots={[slot()]} selected={slot()} open={open} onToggle={() => { open = !open }} onSelect={() => undefined} />)
    const toggle = screen.getByTestId('world3d-speech-toggle')
    assert.equal(toggle.getAttribute('aria-expanded'), 'false')
    assert.equal(toggle.closest('h3')?.textContent?.includes('Voice and lip-sync'), true)
    assert.equal(screen.queryByLabelText('Character'), null)
    fireEvent.click(toggle)
    view.rerender(<Scene3DSpeechSelector slots={[slot()]} selected={slot()} open={open} onToggle={() => { open = !open }} onSelect={() => undefined} />)
    assert.equal(screen.getByTestId('world3d-speech-toggle').getAttribute('aria-expanded'), 'true')
    assert.equal((screen.getByLabelText('Character') as HTMLSelectElement).value, 'subject_1')
  } finally {
    cleanup()
  }
})
