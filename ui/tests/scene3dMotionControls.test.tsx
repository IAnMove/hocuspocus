import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement, Event: dom.window.Event,
})

test('the travel panel edits when a move starts and ends, and clears them', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DMotionControls } = await import('../src/features/scene3d/Scene3DMotionControls')
  const { createDefaultScene3DDocument } = await import('../src/features/scene3d/document')
  const slot = { ...createDefaultScene3DDocument().slots[0], position: [0, 0, 0] as [number, number, number], motion: { to: [0, 0, 6] as [number, number, number], start: 1 } }
  const changes: Array<Record<string, unknown>> = []
  try {
    render(<Scene3DMotionControls slot={slot} duration={4} onChange={patch => changes.push(patch as Record<string, unknown>)} />)
    const start = screen.getByLabelText('Starts at (s)') as HTMLInputElement, end = screen.getByLabelText('Ends at (s)') as HTMLInputElement
    assert.equal(start.value, '1')
    assert.equal(end.value, '')
    assert.equal(end.placeholder, '4.0', 'an empty end is the end of the scene')
    fireEvent.change(end, { target: { value: '3' } })
    assert.deepEqual(changes.at(-1), { motion: { to: [0, 0, 6], start: 1, end: 3 } })
    fireEvent.change(start, { target: { value: '' } })
    assert.deepEqual(changes.at(-1), { motion: { to: [0, 0, 6] } })
    assert.match(screen.getByText(/Straight distance: 6\.0 m · 2\.0 m\/s/).textContent ?? '', /2\.0 m\/s/, 'the speed is over the seconds the move runs: 6 m in 3 s')
  } finally { cleanup() }
})
