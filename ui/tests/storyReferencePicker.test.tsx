import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

Object.assign(globalThis, { React })

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLInputElement: dom.window.HTMLInputElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('reference picker uploads an image and restores focus when closed with Escape', async () => {
  const { render, screen, fireEvent, waitFor, cleanup } = await import('@testing-library/react')
  const { StoryReferencePicker } = await import('../src/features/stories/StoryReferencePicker')
  const originalFetch = globalThis.fetch
  const chosen: string[] = []
  const trigger = document.createElement('button')
  document.body.append(trigger)
  trigger.focus()
  globalThis.fetch = async () => Response.json({ filename: 'hero.png', path: '/uploads/hero.png', url: '/api/v1/uploads/hero.png' })
  try {
    const view = render(<StoryReferencePicker items={[]} workspace="story" disabled={false}
      onChoose={item => chosen.push(item.url)} onClose={() => view.unmount()} />)
    assert.ok(screen.getByRole('dialog'))
    assert.ok(screen.getByRole('button', { name: /From HocusPocus/i }))
    assert.ok(screen.getByRole('button', { name: /From my computer/i }))
    fireEvent.change(screen.getByTestId('asset-input-file'), { target: { files: [new File(['png'], 'hero.png', { type: 'image/png' })] } })
    await waitFor(() => assert.deepEqual(chosen, ['/api/v1/uploads/hero.png']))
    fireEvent.keyDown(document, { key: 'Escape' })
    assert.equal(screen.queryByRole('dialog'), null)
    assert.equal(document.activeElement, trigger)
  } finally { cleanup(); trigger.remove(); globalThis.fetch = originalFetch }
})

test('closing the picker while upload is pending prevents a late reference attachment', async () => {
  const { render, screen, fireEvent, waitFor, act, cleanup } = await import('@testing-library/react')
  const { StoryReferencePicker } = await import('../src/features/stories/StoryReferencePicker')
  const originalFetch = globalThis.fetch
  let finish!: (response: Response) => void
  const chosen: string[] = []
  globalThis.fetch = async () => new Promise<Response>(resolve => { finish = resolve })
  try {
    const view = render(<StoryReferencePicker items={[]} workspace="story" disabled={false}
      onChoose={item => chosen.push(item.url)} onClose={() => view.unmount()} />)
    fireEvent.change(screen.getByTestId('asset-input-file'), { target: { files: [new File(['png'], 'hero.png', { type: 'image/png' })] } })
    await waitFor(() => assert.ok(finish))
    fireEvent.click(screen.getByRole('button', { name: 'Close' }))
    await act(async () => { finish(Response.json({ filename: 'hero.png', path: '/uploads/hero.png', url: '/api/v1/uploads/hero.png' })) })
    assert.deepEqual(chosen, [])
  } finally { cleanup(); globalThis.fetch = originalFetch }
})
