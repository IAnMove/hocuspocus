import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

test('a template document survives the JSON roundtrip', async () => {
  const { documentRoundtrips } = await import('../src/features/scene3d/documentRoundtrip.ts')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates.ts')
  assert.equal(documentRoundtrips(applyScene3DTemplate('speech-portrait')), true)
})

test('the roundtrip check runs once per document, not once per render', { concurrency: false }, async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { useDocumentRoundtrip } = await import('../src/features/scene3d/documentRoundtrip.ts')
  const { applyScene3DTemplate } = await import('../src/features/scene3d/templates.ts')
  type Doc = ReturnType<typeof applyScene3DTemplate>
  let checks = 0
  const check = () => { checks += 1; return true }
  function Probe({ doc, frame }: { doc: Doc; frame: number }) {
    const ok = useDocumentRoundtrip(doc, check)
    return <span data-testid="scene3d-roundtrip">{ok ? 'ok' : 'bad'}:{frame}</span>
  }
  const first = applyScene3DTemplate('speech-portrait')
  try {
    const view = render(<Probe doc={first} frame={0} />)
    // Playback re-renders at 30–60 Hz with the same document.
    for (let frame = 1; frame <= 30; frame += 1) view.rerender(<Probe doc={first} frame={frame} />)
    assert.equal(checks, 1)
    assert.equal(document.querySelector('[data-testid="scene3d-roundtrip"]')?.textContent, 'ok:30')

    view.rerender(<Probe doc={applyScene3DTemplate('speech-dialogue')} frame={31} />)
    assert.equal(checks, 2, 'a new document is checked again')
  } finally {
    cleanup()
  }
})
