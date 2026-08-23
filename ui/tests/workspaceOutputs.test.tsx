import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    url: 'http://localhost/',
  })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    HTMLElement: dom.window.HTMLElement,
    Event: dom.window.Event,
    MutationObserver: dom.window.MutationObserver,
    localStorage: dom.window.localStorage,
  })
}

installDom()

type Deferred<T> = {
  promise: Promise<T>
  resolve: (value: T) => void
}

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(value => { resolve = value })
  return { promise, resolve }
}

function output(name: string) {
  return {
    name,
    type: 'image' as const,
    mode: 'image' as const,
    size: 1,
    created_at: 1,
    url: `/api/v1/file/${name}`,
  }
}

const flushTasks = () => new Promise(resolve => setTimeout(resolve, 0))

test('late output response from workspace A cannot overwrite workspace B', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const originalFetch = globalThis.fetch
  const pending: Record<string, Deferred<Response>> = {}
  const requestedWorkspaces: string[] = []
  let outputFetches = 0
  let aAborted = false

  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), 'http://localhost/')
    if (url.pathname === '/api/v1/workspaces/active') {
      return new Response('{}', { status: 200 })
    }
    if (url.pathname === '/api/v1/workspaces') {
      return new Response(JSON.stringify({
        workspaces: [{ name: 'A', path: '/A' }, { name: 'B', path: '/B' }],
        active: 'B',
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.pathname === '/api/v1/outputs') {
      const workspace = url.searchParams.get('workspace') || ''
      requestedWorkspaces.push(workspace)
      const key = `${workspace}-${outputFetches++}`
      const response = deferred<Response>()
      pending[key] = response
      if (workspace === 'A') {
        assert.ok(init?.signal, 'output request should carry an AbortSignal')
        init?.signal?.addEventListener('abort', () => { aAborted = true })
      }
      return response.promise
    }
    if (url.pathname.includes('/metadata')) {
      return new Response(JSON.stringify({ source: 'none', params: null }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url.pathname}`)
  }

  try {
    useStore.setState({
      activeWorkspace: 'A',
      browsingUploads: false,
      outputs: [],
      outputsTotal: 0,
      outputsLoading: false,
      selectedOutputMeta: null,
    })
    const loadA = useStore.getState().loadOutputs()
    await flushTasks()

    const switchB = useStore.getState().switchWorkspace('B')
    await flushTasks()
    assert.deepEqual(requestedWorkspaces, ['A', 'B'])
    assert.equal(useStore.getState().outputsLoading, true)
    assert.ok(pending['A-0'], 'A response is intentionally resolved last')
    assert.equal(aAborted, true)

    pending['B-1'].resolve(new Response(JSON.stringify({ outputs: [output('B.png')], total: 1 }), {
      headers: { 'content-type': 'application/json' },
    }))
    await switchB
    await flushTasks()
    assert.deepEqual(useStore.getState().outputs.map(item => item.name), ['B.png'])

    pending['A-0'].resolve(new Response(JSON.stringify({ outputs: [output('A.png')], total: 1 }), {
      headers: { 'content-type': 'application/json' },
    }))
    await loadA
    assert.deepEqual(useStore.getState().outputs.map(item => item.name), ['B.png'])
    assert.deepEqual(requestedWorkspaces, ['A', 'B'])
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('a stale workspace list cannot revert a newer explicit switch', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const originalFetch = globalThis.fetch
  const staleWorkspaceList = deferred<Response>()
  let workspaceListReads = 0

  globalThis.fetch = async input => {
    const url = new URL(String(input), 'http://localhost/')
    if (url.pathname === '/api/v1/workspaces/active') {
      return new Response('{}', { status: 200 })
    }
    if (url.pathname === '/api/v1/workspaces') {
      workspaceListReads += 1
      if (workspaceListReads === 1) return staleWorkspaceList.promise
      return new Response(JSON.stringify({
        workspaces: [{ name: 'A', path: '/A' }, { name: 'B', path: '/B' }],
        active: 'B',
      }), { headers: { 'content-type': 'application/json' } })
    }
    if (url.pathname === '/api/v1/outputs') {
      assert.equal(url.searchParams.get('workspace'), 'B')
      return new Response(JSON.stringify({ outputs: [output('B-only.png')], total: 1 }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.pathname.includes('/metadata')) {
      return new Response(JSON.stringify({ source: 'none', params: null }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url.pathname}`)
  }

  try {
    useStore.setState({
      activeWorkspace: 'A',
      browsingUploads: false,
      outputs: [output('A-old.png')],
      outputsTotal: 1,
      outputsLoading: false,
      metadataLoading: true,
      selectedOutputMeta: null,
    })
    const staleLoad = useStore.getState().loadWorkspaces()
    await flushTasks()

    await useStore.getState().switchWorkspace('B')
    await flushTasks()
    assert.equal(useStore.getState().activeWorkspace, 'B')
    assert.deepEqual(useStore.getState().outputs.map(item => item.name), ['B-only.png'])
    assert.equal(useStore.getState().metadataLoading, false)

    staleWorkspaceList.resolve(new Response(JSON.stringify({
      workspaces: [{ name: 'A', path: '/A' }, { name: 'B', path: '/B' }],
      active: 'A',
    }), { headers: { 'content-type': 'application/json' } }))
    await staleLoad
    assert.equal(useStore.getState().activeWorkspace, 'B')
    assert.deepEqual(useStore.getState().outputs.map(item => item.name), ['B-only.png'])
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('switching to an empty workspace invalidates pending metadata without a stuck loader', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const originalFetch = globalThis.fetch
  const staleMetadata = deferred<Response>()

  globalThis.fetch = async input => {
    const url = new URL(String(input), 'http://localhost/')
    if (url.pathname.includes('/metadata')) return staleMetadata.promise
    if (url.pathname === '/api/v1/outputs') {
      assert.equal(url.searchParams.get('workspace'), '__uploads__')
      return new Response(JSON.stringify({ outputs: [], total: 0 }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url.pathname}`)
  }

  try {
    useStore.setState({
      activeWorkspace: 'A',
      browsingUploads: false,
      outputs: [output('A.png')],
      outputsTotal: 1,
      outputsLoading: false,
      metadataLoading: false,
      selectedOutputMeta: null,
    })
    const metadataLoad = useStore.getState().loadOutputMetadata('A.png')
    await flushTasks()
    assert.equal(useStore.getState().metadataLoading, true)

    await useStore.getState().switchWorkspace('__uploads__')
    await flushTasks()
    assert.equal(useStore.getState().metadataLoading, false)

    staleMetadata.resolve(new Response(JSON.stringify({ source: 'sidecar', params: { prompt: 'stale A' } }), {
      headers: { 'content-type': 'application/json' },
    }))
    await metadataLoad
    assert.equal(useStore.getState().selectedOutputMeta, null)
    assert.equal(useStore.getState().metadataLoading, false)
    assert.deepEqual(useStore.getState().outputs, [])
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('a failed workspace switch settles loaders for the still-active workspace', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const originalFetch = globalThis.fetch
  const originalError = console.error
  globalThis.fetch = async input => {
    const url = new URL(String(input), 'http://localhost/')
    if (url.pathname === '/api/v1/workspaces/active') {
      return new Response('{}', { status: 500 })
    }
    throw new Error(`Unexpected request: ${url.pathname}`)
  }
  console.error = () => {}

  try {
    useStore.setState({
      activeWorkspace: 'A',
      browsingUploads: false,
      outputsLoading: true,
      metadataLoading: true,
    })
    await useStore.getState().switchWorkspace('B')
    assert.equal(useStore.getState().activeWorkspace, 'A')
    assert.equal(useStore.getState().outputsLoading, false)
    assert.equal(useStore.getState().metadataLoading, false)
  } finally {
    console.error = originalError
    globalThis.fetch = originalFetch
  }
})

test('a late workspace mutation response cannot alter the same filename in a new view', async () => {
  const { useStore } = await import('../src/stores/useStore.ts')
  const originalFetch = globalThis.fetch
  const staleFavorite = deferred<Response>()

  globalThis.fetch = async input => {
    const url = new URL(String(input), 'http://localhost/')
    if (url.pathname === '/api/v1/favorites/same.png') return staleFavorite.promise
    if (url.pathname === '/api/v1/outputs') {
      assert.equal(url.searchParams.get('workspace'), '__uploads__')
      return new Response(JSON.stringify({ outputs: [{ ...output('same.png'), favorite: false }], total: 1 }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    if (url.pathname.includes('/metadata')) {
      return new Response(JSON.stringify({ source: 'none', params: null }), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`Unexpected request: ${url.pathname}`)
  }

  try {
    useStore.setState({
      activeWorkspace: 'A',
      browsingUploads: false,
      outputs: [{ ...output('same.png'), favorite: false }],
      outputsTotal: 1,
      outputsLoading: false,
    })
    const favoriteA = useStore.getState().toggleFavorite('same.png')
    await flushTasks()
    await useStore.getState().switchWorkspace('__uploads__')
    await flushTasks()

    staleFavorite.resolve(new Response(JSON.stringify({ name: 'same.png', favorite: true }), {
      headers: { 'content-type': 'application/json' },
    }))
    await favoriteA
    assert.equal(useStore.getState().browsingUploads, true)
    assert.equal(useStore.getState().outputs[0]?.favorite, false)
  } finally {
    globalThis.fetch = originalFetch
  }
})
