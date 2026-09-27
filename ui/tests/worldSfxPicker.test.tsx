import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, HTMLCanvasElement: dom.window.HTMLCanvasElement,
  HTMLInputElement: dom.window.HTMLInputElement, Event: dom.window.Event,
  requestAnimationFrame: (fn: FrameRequestCallback) => setTimeout(() => fn(0), 0),
  cancelAnimationFrame: (id: number) => clearTimeout(id),
})

test('world SFX picker shows visual cards and adds an effect', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { WorldSfxControls } = await import('../src/features/sceneFx/WorldSfxControls')
  const added: string[] = []
  try {
    render(<WorldSfxControls cues={[]} duration={8} onChange={cues => { added.push(cues.at(-1)?.kind ?? '') }} onSelect={() => undefined} onDemo={() => undefined} />)
    assert.ok(screen.getByTestId('world-sfx-picker'))
    fireEvent.change(screen.getByLabelText('Search effects'), { target: { value: 'phoenix' } })
    fireEvent.click(screen.getByTestId('world-sfx-add-phoenix'))
    assert.deepEqual(added, ['phoenix'])
  } finally { cleanup() }
})
