import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createCharacterKit, emptyCharacterKitLibrary } from '../src/lib/characterKit.ts'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, HTMLButtonElement: dom.window.HTMLButtonElement,
  Event: dom.window.Event, MutationObserver: dom.window.MutationObserver, ResizeObserver: class { observe() {} disconnect() {} } })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const base = { id: 'ana-base', name: 'Ana', source: '/api/v1/file/ana.png?workspace=w', kind: 'image' as const, alphaStatus: 'transparent' as const, reviewState: 'approved' as const }
const walk = {
  sheet: { source: '/api/v1/file/ana-walk-sheet-1.png?workspace=w', width: 1480, height: 640, count: 4, columns: 4, rows: 1, cell: { width: 370, height: 640 } },
  frames: [{ id: 'contact', source: '/api/v1/file/c.png' }, { id: 'passing', source: '/api/v1/file/p.png' }], fps: 4, loop: 'loop' as const, facing: 'right' as const, reviewState: 'pending' as const,
}

test('the Characters tab lists the animations of a saved character, plays a made one and shows what the card needs', async () => {
  const { render, screen, cleanup, waitFor, fireEvent } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { CharacterAnimationsPanel } = await import('../src/features/characters/CharacterAnimationsPanel.tsx')
  const kit = { ...createCharacterKit('Ana'), id: 'ana', base, animations: { walk } }
  const library = { ...emptyCharacterKitLibrary(), revision: 3, activeId: 'ana', kits: { ana: kit } }
  const original = globalThis.fetch
  globalThis.fetch = (async () => new Response(JSON.stringify(library), { status: 200, headers: { 'Content-Type': 'application/json' } })) as typeof fetch
  useStore.setState({ models: [{ model_type: 'qwen_image_21', name: 'Qwen Image 2.1', family: 'qwen', architecture: 'qwen_image', is_downloaded: true }] as never })
  try {
    render(<CharacterAnimationsPanel workspace="w" />)
    await waitFor(() => assert.ok(screen.getByTestId('animation-walk')))
    assert.ok(screen.getByTestId('animation-angry') && screen.getByTestId('animation-wave'), 'gestures and anime expressions are listed')
    const card = screen.getByTestId('animation-walk')
    assert.match(card.textContent!, /Por revisar|To review/)
    assert.ok(card.querySelector('[data-testid="animation-player"]'), 'a made animation is played from its sheet')
    assert.match(card.textContent!, /walk-cycle-sheet/)
    assert.match(card.textContent!, /frames 4, columns 4, facing right, step 0\.5/)
    const angry = screen.getByTestId('animation-angry')
    assert.match(angry.textContent!, /Sin hacer|Not made/)
    assert.equal((angry.querySelector('button') as HTMLButtonElement).disabled, false, 'it can be made: the character has a picture and a model is installed')
    fireEvent.click(card.querySelectorAll('button')[0])
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})

test('with no saved character the panel says what to do first', async () => {
  const { render, screen, cleanup, waitFor } = await import('@testing-library/react')
  const { CharacterAnimationsPanel } = await import('../src/features/characters/CharacterAnimationsPanel.tsx')
  const original = globalThis.fetch
  globalThis.fetch = (async () => new Response(JSON.stringify(emptyCharacterKitLibrary()), { status: 200, headers: { 'Content-Type': 'application/json' } })) as typeof fetch
  try {
    render(<CharacterAnimationsPanel workspace="empty" />)
    await waitFor(() => assert.match(document.body.textContent!, /Primero crea y guarda un personaje|Create and save a character first/))
    assert.equal(screen.queryByTestId('animation-walk'), null)
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})
