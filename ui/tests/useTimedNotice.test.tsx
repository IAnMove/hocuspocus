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

const wait = (ms: number) => new Promise(resolve => setTimeout(resolve, ms))

test('confirmations hide themselves, errors stay, and a newer notice cancels the older timer', { concurrency: false }, async () => {
  const { render, screen, act, waitFor, cleanup } = await import('@testing-library/react')
  const { useTimedNotice } = await import('../src/features/comics/useTimedNotice.ts')
  type Notify = ReturnType<typeof useTimedNotice>[1]
  let notify: Notify | null = null
  function Probe({ onReady }: { onReady: (value: Notify) => void }) {
    const [notice, set] = useTimedNotice(30)
    useEffect(() => { onReady(set) }, [onReady, set])
    return notice ? <p data-testid="notice">{notice.kind}: {notice.text}</p> : null
  }
  try {
    const view = render(<Probe onReady={value => { notify = value }} />)
    assert.ok(notify)
    act(() => notify!({ kind: 'ok', text: 'saved' }))
    assert.equal(screen.getByTestId('notice').textContent, 'ok: saved')
    await waitFor(() => assert.equal(screen.queryByTestId('notice'), null), { timeout: 500 })

    act(() => notify!({ kind: 'error', text: 'export failed' }))
    await wait(80)
    assert.equal(screen.getByTestId('notice').textContent, 'error: export failed', 'errors do not auto-hide')

    act(() => notify!({ kind: 'ok', text: 'ready' }))
    act(() => notify!({ kind: 'error', text: 'final error' }))
    await wait(80)
    assert.equal(screen.getByTestId('notice').textContent, 'error: final error', 'the stale ok timer was cancelled')

    act(() => notify!(null))
    assert.equal(screen.queryByTestId('notice'), null)

    act(() => notify!({ kind: 'ok', text: 'pending' }))
    view.unmount()
    await wait(60)
  } finally {
    cleanup()
  }
})
