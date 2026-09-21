import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useState } from 'react'
import { JSDOM } from 'jsdom'
import type { ImageWindow } from '../src/features/scene3d/imageWindows'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { React, window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLInputElement: dom.window.HTMLInputElement, SVGElement: dom.window.SVGElement, Event: dom.window.Event, MouseEvent: dom.window.MouseEvent })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('a user can draw and save separate panes, edit one and restore the intact image', async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { Scene3DWindowControls } = await import('../src/features/scene3d/Scene3DWindowControls')
  let saved: ImageWindow[] | undefined
  function Harness() {
    const [windows, setWindows] = useState<ImageWindow[]>()
    return <Scene3DWindowControls sourceUrl="/frame.jpg" windows={windows} disabled={false} onChange={value => { saved = value; setWindows(value) }} />
  }
  try {
    render(<Harness />)
    fireEvent.click(screen.getByText('Transparent windows (0)'))
    const svg = screen.getByRole('img', { name: 'Draw the window outline' })
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 100, height: 100 } as DOMRect)
    assert.equal((screen.getByRole('button', { name: 'Save window' }) as HTMLButtonElement).disabled, true)
    for (const [x, y] of [[10, 10], [45, 10], [45, 90], [10, 90]]) fireEvent.click(svg, { clientX: x, clientY: y })
    fireEvent.click(screen.getByRole('button', { name: 'Save window' }))
    assert.deepEqual(saved, [[[.1, .1], [.45, .1], [.45, .9], [.1, .9]]])
    for (const [x, y] of [[55, 10], [90, 10], [90, 90], [55, 90]]) fireEvent.click(svg, { clientX: x, clientY: y })
    fireEvent.click(screen.getByRole('button', { name: 'Save window' }))
    assert.equal(saved!.length, 2)
    fireEvent.click(screen.getAllByRole('button', { name: 'Edit outline' })[0])
    fireEvent.click(screen.getByRole('button', { name: 'Remove last point' }))
    fireEvent.click(svg, { clientX: 20, clientY: 80 })
    fireEvent.click(screen.getByRole('button', { name: 'Save window' }))
    assert.deepEqual(saved![0][3], [.2, .8])
    assert.deepEqual(saved![1][0], [.55, .1])
    fireEvent.click(screen.getAllByRole('button', { name: 'Close opening' })[0])
    fireEvent.click(screen.getByRole('button', { name: 'Close opening' }))
    assert.equal(saved, undefined)
    assert.equal(screen.getByRole('img', { name: 'Static layer image' }).getAttribute('src'), '/frame.jpg')
  } finally { cleanup() }
})
