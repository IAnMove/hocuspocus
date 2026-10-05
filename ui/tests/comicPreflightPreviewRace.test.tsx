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
    HTMLInputElement: dom.window.HTMLInputElement,
    Event: dom.window.Event,
    CustomEvent: dom.window.CustomEvent,
    MutationObserver: dom.window.MutationObserver,
    localStorage: dom.window.localStorage,
    ResizeObserver: class { observe() {} disconnect() {} },
  })
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
}

installDom()

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(next => { resolve = next })
  return { promise, resolve }
}

const json = (body: unknown) => new Response(JSON.stringify(body), {
  headers: { 'content-type': 'application/json' },
})

test('a slow PRE load for the previous comic never lands on the comic now open', { concurrency: false }, async () => {
  const { render, screen, act, waitFor, cleanup } = await import('@testing-library/react')
  const { ComicVideoPreflightPanel } = await import('../src/features/comics/ComicWorkflowPanels.tsx')
  const { useComicStore } = await import('../src/features/comics/store.ts')
  const { createComicProject } = await import('../src/features/comics/model.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  const previousFetch = globalThis.fetch
  const first = createComicProject()
  const second = createComicProject()
  const firstList = deferred<Response>()
  const requested: string[] = []
  globalThis.fetch = async (input: RequestInfo | URL) => {
    const url = String(input)
    const path = url.slice(url.indexOf('/api'))
    requested.push(path)
    if (path.startsWith('/api/v1/director/pipelines')) {
      return useComicStore.getState().project.id === first.id ? firstList.promise : json({ pipelines: [], total: 0 })
    }
    if (path.startsWith('/api/v1/director/pipeline/')) {
      return json({
        pipeline_id: 'pre-first', status: 'preview_ready', comic_id: first.id,
        preview_fingerprint: 'fp-first', preview_clips: [], quality_gate: null,
      })
    }
    return json({ outputs: [], total: 0, assets: [], pipelines: [] })
  }
  window.localStorage.clear()
  useStore.setState({ activeWorkspace: 'default' } as never)
  useComicStore.setState({ project: first } as never)
  try {
    render(<ComicVideoPreflightPanel notify={() => {}} />)
    await waitFor(() => assert.ok(requested.some(path => path.startsWith('/api/v1/director/pipelines'))))
    assert.ok(screen.getByText('Loading comic PRE…'))

    // The user opens another comic while the first list request is still in flight.
    await act(async () => { useComicStore.setState({ project: second } as never) })
    await waitFor(() => assert.equal(screen.queryByText('Loading comic PRE…'), null))

    // Now the first comic's list arrives with a ready PRE.
    firstList.resolve(json({
      pipelines: [{ id: 'pre-first', pipeline_type: 'comic_movie', status: 'preview_ready', comic_id: first.id }],
      total: 1,
    }))
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)) })

    assert.equal(requested.some(path => path === '/api/v1/director/pipeline/pre-first'), false,
      'the stale load stops before fetching the other comic\'s PRE')
    assert.equal(window.localStorage.getItem(`maestro-comic-preflight:default:${second.id}`), null,
      'the open comic never remembers the other comic\'s PRE id')
    assert.equal(window.localStorage.getItem(`maestro-comic-preflight:default:${first.id}`), null)
    assert.equal(screen.queryByText('Loading comic PRE…'), null, 'the newer load\'s spinner state is untouched')
  } finally {
    cleanup()
    globalThis.fetch = previousFetch
  }
})
