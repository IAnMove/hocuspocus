import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { Scene3DDocument, Scene3DSlot } from '../src/features/scene3d/types.ts'

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

const model = (id: string, extra: Partial<Scene3DSlot> = {}): Scene3DSlot => ({
  id, slot: 'prop', position: [0, 0, 0], rotationY: 0, scale: 1, sourceUrl: `/api/v1/file/${id}.glb?workspace=studio`, media: 'model3d', clip: null, ...extra,
})

function documentWith(slots: Scene3DSlot[]): Scene3DDocument {
  return {
    version: 1, units: 'meters', up: 'y', templateId: 'two-shot', width: 1280, height: 720, fps: 30, duration: 5,
    camera: { family: 'fixed', eye: [0, 1.6, 6], look: [0, 1, 0], fov: 45 },
    light: { kind: 'directional', direction: [-0.4, -1, -0.3], intensity: 1.2, color: '#ffffff' }, slots,
  } as Scene3DDocument
}

test('Sit on sends the same rest binding as world3d.scene.patch and keeps the arranged document', async () => {
  const { render, screen, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  const { Scene3DRestControls } = await import('../src/features/scene3d/Scene3DRestControls.tsx')
  const ana = model('ana', { character: { id: 'ana', name: 'Ana' } })
  const scene = documentWith([ana, model('chair', { furniture: { kind: 'chair' }, scale: 0.53 }), model('table', { scale: 0.44 })])
  const seated = documentWith([{ ...ana, rest: { pose: 'sit', on: 'chair' }, position: [0.4, 0, 0], rotationY: 1.2, grounded: false }, ...scene.slots.slice(1)])
  const sent: Array<Record<string, unknown>> = []
  const original = globalThis.fetch
  globalThis.fetch = (async (_url: string, init?: RequestInit) => {
    sent.push(JSON.parse(String(init?.body)))
    return new Response(JSON.stringify({ version: 1, document: seated, warnings: ['at_height_unusual: table is high', 'other: kept out'], layout: {} }),
      { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  const arranged: Scene3DDocument[] = []
  try {
    render(<Scene3DRestControls slot={ana} document={scene} workspace="studio" locked={false} onArranged={next => arranged.push(next)} />)
    const select = screen.getByRole('combobox', { name: 'Sit on ana' }) as HTMLSelectElement
    assert.deepEqual([...select.options].map(option => option.value), ['', 'chair', 'table'])
    fireEvent.change(select, { target: { value: 'chair' } })
    await waitFor(() => assert.equal(arranged.length, 1))
    assert.equal(sent[0].workspace, 'studio')
    assert.deepEqual(sent[0].bindings, [{ object_id: 'ana', rest: { pose: 'sit', on: 'chair' } }])
    assert.equal((sent[0].document as Scene3DDocument).slots.length, 3)
    const sitter = arranged[0].slots.find(item => item.id === 'ana')
    assert.deepEqual(sitter?.rest, { pose: 'sit', on: 'chair' })
    assert.deepEqual(sitter?.position, [0.4, 0, 0])
    assert.ok(screen.getByText('at_height_unusual: table is high'))
    assert.equal(screen.queryByText('other: kept out'), null)
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})

test('Real height sends height in metres and Standing sends rest null', async () => {
  const { render, screen, fireEvent, cleanup, waitFor } = await import('@testing-library/react')
  const { Scene3DRestControls } = await import('../src/features/scene3d/Scene3DRestControls.tsx')
  const ana = model('ana', { rest: { pose: 'sit', on: 'chair', at: 'table' } })
  const scene = documentWith([ana, model('chair'), model('table')])
  const sent: Array<Record<string, unknown>> = []
  const original = globalThis.fetch
  globalThis.fetch = (async (_url: string, init?: RequestInit) => {
    sent.push(JSON.parse(String(init?.body)))
    return new Response(JSON.stringify({ version: 1, document: scene, warnings: [] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
  }) as typeof fetch
  try {
    render(<Scene3DRestControls slot={ana} document={scene} workspace="studio" locked={false} onArranged={() => {}} />)
    assert.equal((screen.getByRole('combobox', { name: 'At the table ana' }) as HTMLSelectElement).value, 'table')
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Real height (m) ana' }), { target: { value: '1.62' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply height' }))
    await waitFor(() => assert.equal(sent.length, 1))
    assert.deepEqual(sent[0].bindings, [{ object_id: 'ana', height: 1.62 }])
    await waitFor(() => assert.equal((screen.getByRole('combobox', { name: 'Sit on ana' }) as HTMLSelectElement).disabled, false))
    fireEvent.change(screen.getByRole('combobox', { name: 'Sit on ana' }), { target: { value: '' } })
    await waitFor(() => assert.equal(sent.length, 2))
    assert.deepEqual(sent[1].bindings, [{ object_id: 'ana', rest: null }])
  } finally {
    globalThis.fetch = original
    cleanup()
  }
})
