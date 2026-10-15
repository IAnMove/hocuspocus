// SFX video reference: the guide stays in the form when the panel unmounts (SFX -> Speech/Music/Mixer -> SFX),
// but the picker's value was component state. An uploaded clip is not among the workspace outputs the panel
// falls back to, so the clip came back as a raw /api/v1/uploads/... text instead of an attached file.
import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement, HTMLInputElement: dom.window.HTMLInputElement,
  File: dom.window.File, Event: dom.window.Event, MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} }, React,
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

const GUIDE = '/api/v1/uploads/street-clip.mp4'

test('an uploaded SFX clip is still shown as the attached file after the panel is remounted', { concurrency: false }, async () => {
  const { render, cleanup, fireEvent, act, waitFor } = await import('@testing-library/react')
  const { SfxControls } = await import('../src/components/Sidebar/SfxControls.tsx')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = String(input)
    if (url.includes('/api/v1/upload')) {
      return new Response(JSON.stringify({ filename: 'street-clip.mp4', path: '/uploads/street-clip.mp4', url: GUIDE }), { headers: { 'content-type': 'application/json' } })
    }
    return new Response(JSON.stringify({ total: 0, assets: [], outputs: [] }), { headers: { 'content-type': 'application/json' } })
  }) as typeof fetch
  useStore.setState({ activeWorkspace: 'sfx-guide', params: {}, durationSeconds: 8 } as never)
  try {
    const first = render(<SfxControls />)
    const file = new File(['x'], 'street-clip.mp4', { type: 'video/mp4' })
    await act(async () => { fireEvent.change(first.getByTestId('asset-input-file'), { target: { files: [file] } }) })
    await waitFor(() => assert.equal(useStore.getState().params.video_guide, GUIDE))
    assert.ok(first.getAllByText('street-clip.mp4').length >= 1, 'the chosen clip is shown by name')
    assert.equal(first.queryByText(GUIDE), null)

    cleanup()                                   // the panel unmounts when another sub-tab opens
    document.body.innerHTML = ''
    const second = render(<SfxControls />)      // ... and mounts again with the guide still in the form
    assert.equal(useStore.getState().params.video_guide, GUIDE)
    assert.ok(second.getAllByText('street-clip.mp4').length >= 1, 'the clip is attached again, by name')
    assert.equal(second.queryByText(GUIDE), null, 'no raw upload URL')
  } finally {
    cleanup()
    document.body.innerHTML = ''
    globalThis.fetch = previousFetch
  }
})
