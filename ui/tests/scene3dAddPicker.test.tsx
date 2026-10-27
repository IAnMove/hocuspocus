import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { TEXT_TEMPLATES } from '../src/lib/kineticText'
import { FX_CATALOG } from '../src/features/sceneFx/types'
import { WORLD_SFX_KINDS } from '../src/features/sceneFx/world'
import { addPickerCatalog } from '../src/features/scene3d/addPickerCatalog'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React,
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  Event: dom.window.Event,
  MutationObserver: dom.window.MutationObserver,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('the add picker still lists every old effect, demo and text template id', () => {
  const ids = new Set(addPickerCatalog().map(item => item.id))
  const missing: string[] = []
  for (const kind of WORLD_SFX_KINDS) if (!ids.has(`world:${kind}`)) missing.push(`world:${kind}`)
  for (const item of FX_CATALOG) if (!ids.has(`overlay:${item.id}`)) missing.push(`overlay:${item.id}`)
  for (const id of ['world-demo:depth', 'world-demo:duel', 'world-demo:mixed', 'showcase:all', 'showcase:anime', 'showcase:retro']) {
    if (!ids.has(id)) missing.push(id)
  }
  for (const template of TEXT_TEMPLATES) if (!ids.has(`text:${template.id}`)) missing.push(`text:${template.id}`)
  assert.deepEqual(missing, [])
  assert.ok(ids.size > 150)
})

test('searching the picker finds one effect and picking it reports that item', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DAddPicker } = await import('../src/features/scene3d/Scene3DAddPicker')
  let picked = ''
  try {
    render(<Scene3DAddPicker open onPick={item => { picked = item.id }} onClose={() => undefined} />)
    fireEvent.change(screen.getByLabelText('Search'), { target: { value: 'phoenix' } })
    const button = screen.getByTestId('scene3d-add-item-world:phoenix')
    assert.equal(screen.queryByTestId('scene3d-add-item-world:rain'), null)
    fireEvent.click(button)
    assert.equal(picked, 'world:phoenix')
  } finally {
    cleanup()
  }
})
