import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { createCharacterKit } from '../src/lib/characterKit'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, sessionStorage: dom.window.sessionStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} } })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

for (const mounted of [true, false]) test(`save all merges voice and ${mounted ? 'open' : 'recovered'} mouth workshop in one write before returning`, async t => {
  const { render, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { CharacterEditorSession } = await import('../src/features/characters/CharacterEditorSession')
  const { useCharacterEditorHandoff, characterEditorHasUnsavedChanges } = await import('../src/features/characters/characterEditorHandoff')
  const { writeSpeechDraft, readSpeechDraft, clearSpeechDraft } = await import('../src/lib/characterSpeechDraft')
  const kit = createCharacterKit('Test character')
  kit.id = 'save-all-character'
  kit.base = { id: 'base', name: 'Base', source: '/base.png', kind: 'image', alphaStatus: 'transparent', reviewState: 'approved' }
  let library = { version: 1 as const, revision: 3, activeId: kit.id, kits: { [kit.id]: kit } }
  const edited = { ...kit, mouth: { wide: { id: 'mouth', name: 'Mouth', source: '/edited-mouth.png', kind: 'overlay' as const,
    alphaStatus: 'transparent' as const, reviewState: 'pending' as const } },
    anchors: { base: { mouth: { offsetX: 4, offsetY: -20, scale: .08, rotation: 0 } } } }
  writeSpeechDraft('source', { baseRevision: 3, kit: edited }, kit.id)
  let writes = 0, linked = false, returned = false, rejectSave = true
  const originalFetch = globalThis.fetch
  globalThis.fetch = async (input, init) => {
    const url = String(input)
    if (url.includes('/character-kits/library')) {
      if (init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body)); writes++
        assert.equal(body.baseRevision, 3)
        assert.equal(body.kit.voice.voiceId, 'serena')
        assert.deepEqual(body.kit.mouth, edited.mouth)
        assert.deepEqual(body.kit.anchors, edited.anchors)
        assert.equal(body.kit.base.reviewState, 'approved')
        if (rejectSave) return new Response(JSON.stringify({ detail: 'Concurrent change; reload required' }), { status: 409 })
        library = { ...library, revision: 4, kits: { [kit.id]: body.kit } }
      }
      return new Response(JSON.stringify(library))
    }
    if (url.includes('/outputs')) return new Response(JSON.stringify({ outputs: [], total: 0 }))
    if (url.endsWith('/mouths/manifest.json')) return new Response(JSON.stringify({ packs: [] }))
    throw new Error(`Unexpected request: ${init?.method || 'GET'} ${url}`)
  }
  const request = { workspace: 'source', kit, sourceId: 'source/series/character', sourceLabel: 'Test series',
    onSaved: async () => { assert.equal(library.revision, 4); linked = true },
    onReturn: async () => { assert.equal(linked, true); returned = true } }
  useCharacterEditorHandoff.setState({ request })
  t.after(() => { cleanup(); globalThis.fetch = originalFetch; clearSpeechDraft('source', kit.id); useCharacterEditorHandoff.setState({ request: null }) })
  const view = render(<CharacterEditorSession request={request} />)
  await waitFor(() => assert.equal(view.getByTestId('save-character').hasAttribute('disabled'), false))
  if (mounted) {
    fireEvent.click(view.getByRole('button', { name: 'Configure 2D mouth and lip sync' }))
    await view.findByRole('region', { name: 'Prepare 2D speech' })
    await waitFor(() => assert.equal(view.getByRole('button', { name: 'Save everything and return to Series Lab' }).hasAttribute('disabled'), false))
  }
  fireEvent.change(view.getByTestId('character-voice'), { target: { value: 'serena' } })
  fireEvent.click(view.getByRole('button', { name: 'Save everything and return to Series Lab' }))
  await view.findAllByText(/Concurrent change; reload required/)
  assert.equal(writes, 1); assert.equal(returned, false); assert.equal(linked, false)
  assert.ok(readSpeechDraft('source', kit.id), 'failed save retains recovery')
  assert.equal(characterEditorHasUnsavedChanges(request), true)
  rejectSave = false
  await waitFor(() => assert.equal(view.getByRole('button', { name: 'Save everything and return to Series Lab' }).hasAttribute('disabled'), false))
  fireEvent.click(view.getByRole('button', { name: 'Save everything and return to Series Lab' }))
  await waitFor(() => assert.equal(returned, true))
  assert.equal(writes, 2, 'one request for each explicit click, with no automatic retry or duplicate save')
  assert.equal(readSpeechDraft('source', kit.id), null)
  assert.equal(useCharacterEditorHandoff.getState().request, null)
  assert.equal(characterEditorHasUnsavedChanges(request), false)
})
