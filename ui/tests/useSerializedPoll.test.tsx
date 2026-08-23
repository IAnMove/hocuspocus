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

test('serializes polls when latency exceeds the interval', { concurrency: false }, async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { useSerializedPoll } = await import('../src/hooks/useSerializedPoll.ts')
  let inFlight = 0
  let maximumInFlight = 0
  let requests = 0

  function Probe() {
    useSerializedPoll({
      intervalMs: 10,
      poll: async () => {
        inFlight += 1
        maximumInFlight = Math.max(maximumInFlight, inFlight)
        await new Promise(resolve => window.setTimeout(resolve, 35))
        inFlight -= 1
        requests += 1
        return requests
      },
      onValue: () => {},
    })
    return null
  }

  render(<Probe />)
  await new Promise(resolve => window.setTimeout(resolve, 100))
  cleanup()
  assert.equal(maximumInFlight, 1)
})

test('ignores a response from an old owner', { concurrency: false }, async () => {
  const { render, waitFor, cleanup } = await import('@testing-library/react')
  const { useSerializedPoll } = await import('../src/hooks/useSerializedPoll.ts')
  const requests: Array<{ resolve: (value: string) => void }> = []
  const values: string[] = []

  function Probe({ owner }: { owner: string }) {
    useSerializedPoll({
      ownerKey: owner,
      poll: () => new Promise(resolve => requests.push({ resolve })),
      onValue: value => values.push(value),
    })
    return null
  }

  const view = render(<Probe owner="old" />)
  await waitFor(() => assert.equal(requests.length, 1))
  view.rerender(<Probe owner="new" />)
  await waitFor(() => assert.equal(requests.length, 2))
  requests[1].resolve('new')
  await waitFor(() => assert.deepEqual(values, ['new']))
  requests[0].resolve('old')
  await new Promise(resolve => window.setTimeout(resolve, 0))
  assert.deepEqual(values, ['new'])
  cleanup()
})

test('aborts and ignores a pending response after unmount', { concurrency: false }, async () => {
  const { render, cleanup } = await import('@testing-library/react')
  const { useSerializedPoll } = await import('../src/hooks/useSerializedPoll.ts')
  let resolveRequest!: (value: string) => void
  let requestSignal: AbortSignal | undefined
  const values: string[] = []

  function Probe() {
    useSerializedPoll({
      poll: signal => {
        requestSignal = signal
        return new Promise(resolve => { resolveRequest = resolve })
      },
      onValue: value => values.push(value),
    })
    return null
  }

  const view = render(<Probe />)
  view.unmount()
  resolveRequest('late')
  await new Promise(resolve => window.setTimeout(resolve, 0))
  assert.equal(requestSignal?.aborted, true)
  assert.deepEqual(values, [])
  cleanup()
})
