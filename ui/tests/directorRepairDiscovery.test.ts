// A page reload loses the Director repair polls while the repair itself keeps running on the server.
// The slice documents that a reload rediscovers active repairs "without requiring the Dashboard to be
// opened first", but the discovery only ran inside loadPipelineList, which boot never calls.
import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
window.matchMedia = (() => ({ matches: false })) as typeof window.matchMedia
const { useStore } = await import('../src/stores/useStore')
const { disposeDirectorRepairPolls } = await import('../src/features/director/store/directorDashboardSlice')

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
const repairing = { id: 'p-repair', status: 'completed', repair_status: 'running' }
const idle = { id: 'p-idle', status: 'completed', repair_status: null }
const finished = { id: 'p-finished', status: 'completed', repair_status: 'queued' }

async function withDirector(run: (polled: Array<[string, string]>) => Promise<void>, list = [idle, repairing, finished]) {
  const before = useStore.getState(), beforeFetch = globalThis.fetch
  const polled: Array<[string, string]> = []
  try {
    globalThis.fetch = (async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/director/pipelines/active')) return json({ pipelines: [] })
      if (url.includes('/director/pipelines/p-repair')) return json({ id: 'p-repair', repair: { status: 'running', operation_id: 'op-1' } })
      // The operation ended between the list and the detail request.
      if (url.includes('/director/pipelines/p-finished')) return json({ id: 'p-finished', repair: { status: 'completed', operation_id: 'op-2' } })
      if (url.includes('/director/pipelines')) return json({ pipelines: list, total: list.length })
      return json({})
    }) as typeof fetch
    useStore.setState({ pipelineId: null, directorEditorDetached: false, dashboardPipelineList: [],
      pollPipelineRepair: (pid: string, operationId: string) => { polled.push([pid, operationId]) },
      maybeRefreshGallery: async () => {} } as never)
    await run(polled)
  } finally {
    await new Promise(resolve => setTimeout(resolve, 20))
    disposeDirectorRepairPolls()
    useStore.setState(before); globalThis.fetch = beforeFetch
  }
}

test('boot rediscovers an active Director repair without opening the Dashboard', async () => {
  await withDirector(async polled => {
    await useStore.getState().reconnectDirectorPipelines()
    await new Promise(resolve => setTimeout(resolve, 50))
    assert.deepEqual(polled, [['p-repair', 'op-1']])
    assert.equal(useStore.getState().dashboardSelectedPipeline, null, 'discovery must not open or select a run')
    assert.equal(useStore.getState().dashboardOpen, false)
  })
})

test('a repair that already ended is reflected in the list instead of being polled', async () => {
  await withDirector(async polled => {
    useStore.setState({ dashboardPipelineList: [finished] } as never)
    useStore.getState().discoverActiveDirectorRepairs([finished] as never)
    await new Promise(resolve => setTimeout(resolve, 50))
    assert.deepEqual(polled, [])
    assert.equal(useStore.getState().dashboardPipelineList[0]?.repair_status, 'completed')
  })
})

test('a failing run list does not break the boot reconnect', async () => {
  const before = useStore.getState(), beforeFetch = globalThis.fetch
  try {
    globalThis.fetch = (async (input: RequestInfo | URL) => String(input).includes('/director/pipelines/active')
      ? json({ pipelines: [] }) : json({ detail: 'down' }, 500)) as typeof fetch
    await assert.doesNotReject(useStore.getState().reconnectDirectorPipelines())
    await new Promise(resolve => setTimeout(resolve, 30))
  } finally {
    useStore.setState(before); globalThis.fetch = beforeFetch
  }
})
