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
    HTMLButtonElement: dom.window.HTMLButtonElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function Explodes({ when }: { when: boolean }) {
  if (when) throw new Error('render blew up')
  return <p>healthy</p>
}

test('the boundary shows the error with reload and copy, and a scoped one can retry', { concurrency: false }, async () => {
  const { render, screen, fireEvent, cleanup } = await import('@testing-library/react')
  const { AppErrorBoundary } = await import('../src/components/AppErrorBoundary.tsx')
  const previousFetch = globalThis.fetch
  const previousError = console.error
  const reported: Array<Record<string, unknown>> = []
  globalThis.fetch = async (_input: RequestInfo | URL, init?: RequestInit) => {
    reported.push(JSON.parse(String(init?.body)))
    return new Response('{"status":"ok"}', { headers: { 'content-type': 'application/json' } })
  }
  console.error = () => {}
  const copied: string[] = []
  Object.defineProperty(navigator, 'clipboard', {
    configurable: true,
    value: { writeText: async (text: string) => { copied.push(text) } },
  })
  try {
    let when = true
    const view = render(<AppErrorBoundary scope="gallery"><Explodes when={when} /></AppErrorBoundary>)
    const alert = screen.getByRole('alert')
    assert.match(alert.textContent ?? '', /Something went wrong in this view/)
    assert.match(alert.textContent ?? '', /render blew up/)
    assert.ok(screen.getByRole('button', { name: /Reload/ }))
    assert.equal(reported.length, 1)
    assert.equal(reported[0].control_type, 'boundary:gallery')
    assert.match(String(reported[0].control), /render blew up/)

    fireEvent.click(screen.getByRole('button', { name: /Copy error/ }))
    await screen.findByRole('button', { name: /Copied/ })
    assert.match(copied[0], /render blew up/)

    when = false
    view.rerender(<AppErrorBoundary scope="gallery"><Explodes when={when} /></AppErrorBoundary>)
    fireEvent.click(screen.getByRole('button', { name: /Retry/ }))
    assert.ok(screen.getByText('healthy'))
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
    console.error = previousError
  }
})

test('the root boundary offers no retry', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { AppErrorBoundary } = await import('../src/components/AppErrorBoundary.tsx')
  const previousError = console.error
  const previousFetch = globalThis.fetch
  globalThis.fetch = async () => new Response('{}')
  console.error = () => {}
  try {
    render(<AppErrorBoundary><Explodes when /></AppErrorBoundary>)
    assert.ok(screen.getByRole('alert'))
    assert.equal(screen.queryByRole('button', { name: /Retry/ }), null)
  } finally {
    cleanup()
    console.error = previousError
    globalThis.fetch = previousFetch
  }
})

test('a new tab clears a shown error without remounting a panel that keeps working', { concurrency: false }, async () => {
  const { render, screen, cleanup } = await import('@testing-library/react')
  const { AppErrorBoundary } = await import('../src/components/AppErrorBoundary.tsx')
  const previousError = console.error
  const previousFetch = globalThis.fetch
  globalThis.fetch = async () => new Response('{}')
  console.error = () => {}
  let mounts = 0
  function Worker() {
    React.useEffect(() => { mounts += 1 }, [])
    return <p>working</p>
  }
  try {
    const view = render(<AppErrorBoundary scope="lips" resetKey="studio:lips"><Worker /></AppErrorBoundary>)
    view.rerender(<AppErrorBoundary scope="characters" resetKey="studio:characters"><Worker /></AppErrorBoundary>)
    assert.ok(screen.getByText('working'))
    assert.equal(mounts, 1, 'switching tabs must not restart a running sequence')
    view.rerender(<AppErrorBoundary scope="characters" resetKey="studio:characters"><Explodes when /></AppErrorBoundary>)
    assert.ok(screen.getByRole('alert'))
    view.rerender(<AppErrorBoundary scope="lips" resetKey="studio:lips"><Worker /></AppErrorBoundary>)
    assert.ok(screen.getByText('working'), 'the next tab starts without the old error')
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
    console.error = previousError
  }
})
