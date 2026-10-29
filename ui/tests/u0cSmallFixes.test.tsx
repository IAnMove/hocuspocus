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
}

installDom()

test('a saved view or an uploaded file is a Face Rig subject; a preview is not', async () => {
  const { faceRigHasSubject } = await import('../src/features/characters/faceRigSubject.ts')
  const blob = [{ id: 'front', url: 'blob:preview' }]
  assert.equal(faceRigHasSubject([], [], null), false)
  assert.equal(faceRigHasSubject([{ id: 'front', url: 'data:image/png;base64,aa' }], [], 'front'), false)
  assert.equal(faceRigHasSubject(blob, [], 'front'), false)
  assert.equal(faceRigHasSubject([{ id: 'side', url: 'blob:side' }, { id: 'front', url: '/turn.png' }], [], 'side'), false)
  assert.equal(faceRigHasSubject([{ id: 'front', url: '/turn.png' }], [], 'front'), true)
  assert.equal(faceRigHasSubject([{ id: 'front', filename: 'sheet.png' }], [], null), true)
  assert.equal(faceRigHasSubject(blob, [{ path: 'uploads/nerea.png' }], 'front'), true)
  assert.equal(faceRigHasSubject(blob, [{ file: { name: 'nerea.png' } }], 'front'), true)
})

test('Face Rig stays disabled until there is a subject image and still names the other waits', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { FaceRigOpenButton } = await import('../src/features/characters/FaceRigOpenButton.tsx')
  const name = 'Create / open CharacterKit Face Rig'
  const needImage = 'Capture a turnaround view or upload the subject image first.'
  try {
    const blocked = render(<FaceRigOpenButton hasSubject={false} busy={false} onClick={() => undefined} />)
    const waiting = screen.getByRole('button', { name }) as HTMLButtonElement
    assert.equal(waiting.disabled, true)
    assert.equal(waiting.title, needImage)
    blocked.unmount()
    let clicks = 0
    const open = render(<FaceRigOpenButton hasSubject busy={false} onClick={() => { clicks += 1 }} />)
    const ready = screen.getByRole('button', { name }) as HTMLButtonElement
    assert.equal(ready.disabled, false)
    assert.equal(ready.getAttribute('title'), null)
    fireEvent.click(ready)
    assert.equal(clicks, 1)
    open.unmount()
    render(<FaceRigOpenButton hasSubject busy onClick={() => undefined} />)
    const working = screen.getByRole('button', { name }) as HTMLButtonElement
    assert.equal(working.disabled, true)
    assert.equal(working.title, 'Wait until the current action finishes')
  } finally {
    cleanup()
  }
})

test('a character import card keeps the name and the action apart', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { createCharacterKit, emptyCharacterKitLibrary } = await import('../src/lib/characterKit.ts')
  const { LipsCreatorPanel } = await import('../src/features/characters/LipsCreatorPanel.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const nerea = createCharacterKit('Nerea')
  nerea.mouth.closed = { id: 'mouth', name: 'closed', source: '/m.png', kind: 'image', alphaStatus: 'unknown', reviewState: 'approved' }
  const characters = { ...emptyCharacterKitLibrary(), kits: { [nerea.id]: nerea } }
  const originalFetch = globalThis.fetch
  globalThis.fetch = async input => {
    const url = String(input)
    const body = url.includes('lips-creator') ? emptyCharacterKitLibrary() : characters
    return { ok: true, json: async () => body } as Response
  }
  useStore.setState({ activeWorkspace: 'lab' })
  try {
    render(<LipsCreatorPanel />)
    const card = await screen.findByRole('button', { name: 'Nerea. Import and edit' })
    assert.match(card.className, /flex-col/)
    const lines = [...card.querySelectorAll('p')].map(node => node.textContent)
    assert.deepEqual(lines, ['Nerea', 'Import and edit'])
    assert.equal(screen.queryByRole('button', { name: 'NereaImport and edit' }), null)
  } finally {
    cleanup()
    globalThis.fetch = originalFetch
  }
})
