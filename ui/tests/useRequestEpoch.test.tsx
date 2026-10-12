import assert from 'node:assert/strict'
import test from 'node:test'
import React, { useEffect } from 'react'
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

test('only the newest request stays fresh, and unmount retires all of them', { concurrency: false }, async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { useRequestEpoch } = await import('../src/hooks/useRequestEpoch.ts')
  type Begin = () => () => boolean
  let begin: Begin | null = null
  function Probe({ onReady }: { onReady: (value: Begin) => void }) {
    const value = useRequestEpoch()
    useEffect(() => { onReady(value) }, [onReady, value])
    return null
  }
  const onReady = (value: Begin) => { begin = value }
  try {
    const view = render(<Probe onReady={onReady} />)
    assert.ok(begin)
    const first = begin!()
    assert.equal(first(), false, 'a single request is fresh')
    const second = begin!()
    assert.equal(first(), true, 'an older request is stale once a newer one begins')
    assert.equal(second(), false)
    view.rerender(<Probe onReady={onReady} />)
    assert.equal(second(), false, 're-rendering does not retire the request')
    view.unmount()
    assert.equal(second(), true, 'unmounting retires the live request')
  } finally {
    cleanup()
  }
})
