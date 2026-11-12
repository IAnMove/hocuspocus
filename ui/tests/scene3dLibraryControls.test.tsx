import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createDefaultScene3DDocument } from '../src/features/scene3d/document'
const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement, HTMLImageElement: dom.window.HTMLImageElement,
  Event: dom.window.Event, MouseEvent: dom.window.MouseEvent, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
const originalFetch = globalThis.fetch
test.afterEach(() => { globalThis.fetch = originalFetch })

for (const change of ['cancel', 'workspace', 'edit']) test(`a delayed scene load cannot replace the scene after ${change}`, async () => {
  const { render, screen, fireEvent, waitFor, act, cleanup } = await import('@testing-library/react')
  const { Scene3DLibraryControls } = await import('../src/features/scene3d/Scene3DLibraryControls')
  const name = 'Gandalf-17-' + 'a'.repeat(32) + '.world3d.scene.json'
  const file = { name, type: 'scene', mode: null, size: 100, created_at: 1, url: '/scene.json' }
  let release: ((response: Response) => void) | undefined, commits = 0
  globalThis.fetch = async url => {
    if (String(url).includes('/outputs?')) return Response.json({ outputs: [file], total: 1 })
    if (String(url).includes('/working-scenes?')) return Response.json({ scenes: [] })
    assert.ok(String(url).includes('workspace=one'))
    return new Promise<Response>(resolve => { release = resolve })
  }
  const props = { document: createDefaultScene3DDocument(), workspace: 'one', disabled: false, preview: () => undefined, onLoad: () => { commits++ } }
  try {
    const view = render(<Scene3DLibraryControls {...props} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open scene' }))
    await waitFor(() => assert.ok(document.querySelector(`button[title="${name}"]`)))
    fireEvent.click(document.querySelector(`button[title="${name}"]`)!)
    fireEvent.click(screen.getByRole('button', { name: 'Choose', exact: true }))
    await waitFor(() => assert.ok(release))
    if (change === 'cancel') fireEvent.click(screen.getByRole('button', { name: 'Cancel loading', exact: true }))
    if (change === 'workspace') view.rerender(<Scene3DLibraryControls {...props} workspace="two" />)
    if (change === 'edit') view.rerender(<Scene3DLibraryControls {...props} document={{ ...props.document, duration: 9 }} />)
    await act(async () => release!(Response.json(props.document)))
    assert.equal(commits, 0)
  } finally { cleanup() }
})


test('confirm closes the picker but still loads the chosen scene', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { Scene3DLibraryControls } = await import('../src/features/scene3d/Scene3DLibraryControls')
  const name = 'Chosen-' + 'b'.repeat(32) + '.world3d.scene.json'
  const next = { ...createDefaultScene3DDocument(), duration: 9 }
  let loaded = 0
  globalThis.fetch = async url => String(url).includes('/outputs?')
    ? Response.json({ outputs: [{ name, type: 'scene', mode: null, size: 100, created_at: 1, url: '/unused' }], total: 1 })
    : String(url).includes('/working-scenes?') ? Response.json({ scenes: [] }) : Response.json(next)
  try {
    render(<Scene3DLibraryControls document={createDefaultScene3DDocument()} workspace="one" disabled={false} preview={() => undefined} onLoad={doc => { loaded = doc.duration }} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open scene' }))
    await waitFor(() => assert.ok(document.querySelector(`button[title="${name}"]`)))
    fireEvent.click(document.querySelector(`button[title="${name}"]`)!)
    fireEvent.click(screen.getByRole('button', { name: 'Choose', exact: true }))
    await waitFor(() => assert.equal(loaded, 9))
  } finally { cleanup() }
})

test('an unpublished working scene of an agent is listed and opens its current revision', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { Scene3DLibraryControls } = await import('../src/features/scene3d/Scene3DLibraryControls')
  const working = { ...createDefaultScene3DDocument(), duration: 7 }
  const posted: string[] = []
  globalThis.fetch = async (url, init) => {
    if (String(url).includes('/outputs?')) return Response.json({ outputs: [], total: 0 })
    if (String(url).includes('/working-scenes?')) {
      return Response.json({ scenes: [{ sceneId: 'w3d-0123456789ab', revision: 3, templateId: 'cine-dolly-zoom', title: 'Dolly zoom', updatedAt: 5 }] })
    }
    posted.push(String(init?.body))
    return Response.json({ result: { scene: { document: working } } })
  }
  let loaded = 0
  try {
    render(<Scene3DLibraryControls document={createDefaultScene3DDocument()} workspace="one" disabled={false} preview={() => undefined}
      onLoad={doc => { loaded = doc.duration }} />)
    fireEvent.click(screen.getByRole('button', { name: 'Open scene' }))
    await waitFor(() => assert.ok(document.querySelector('button[title="w3d-0123456789ab"]')))
    assert.ok(screen.getAllByText(/Dolly zoom · working scene, not published \(revision 3\)/).length)
    fireEvent.click(document.querySelector('button[title="w3d-0123456789ab"]')!)
    fireEvent.click(screen.getByRole('button', { name: 'Choose', exact: true }))
    await waitFor(() => assert.equal(loaded, 7))
    assert.deepEqual(JSON.parse(posted[0]).input, { workspace: 'one', scene_id: 'w3d-0123456789ab' })
  } finally { cleanup() }
})
