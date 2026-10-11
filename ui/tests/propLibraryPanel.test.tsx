import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, HTMLInputElement: dom.window.HTMLInputElement, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
test('prop palette lists, filters and adds approved objects at real height', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { PropLibraryPanel, propSlot } = await import('../src/features/scene3d/PropLibraryPanel')
  const original = globalThis.fetch
  const lamp = { id: 'lamp', name: 'Lamp', description: 'Desk light', style: 'paper', approved: true, heightM: .4, file: 'lamp.png' }
  globalThis.fetch = async () => new Response(JSON.stringify({ result: { revision: 1, props: [lamp, { ...lamp, id: 'cup', name: 'Cup', description: 'Mug' }] } }))
  let added = ''
  try {
    render(<PropLibraryPanel workspace="demo" onAdd={prop => { added = prop.id }} />)
    await screen.findByText(/Lamp ·/)
    fireEvent.change(screen.getByLabelText('Search props'), { target: { value: 'light' } })
    assert.equal(screen.queryByText(/Cup ·/), null)
    fireEvent.click(screen.getByRole('button', { name: 'Add prop' }))
    assert.equal(added, 'lamp'); assert.equal(propSlot(lamp, 'demo').scale, .2)
  } finally { globalThis.fetch = original; cleanup() }
})
