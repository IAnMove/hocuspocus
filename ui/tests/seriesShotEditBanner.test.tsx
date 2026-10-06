import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import { episode, jsonResponse, series, shot, take } from './seriesReviewFixtures'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document, localStorage: dom.window.localStorage, sessionStorage: dom.window.sessionStorage,
  HTMLElement: dom.window.HTMLElement, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent, MutationObserver: dom.window.MutationObserver })
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })

test('a video exported after opening a shot in the editor becomes that shot\'s take', { concurrency: false }, async t => {
  const { render, cleanup, fireEvent, waitFor } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore')
  const { useSeriesStore } = await import('../src/features/series/store')
  const { setShotEditSession, useShotEditSession } = await import('../src/features/series/shotEditSession')
  const { SeriesShotEditBanner } = await import('../src/features/series/SeriesShotEditBanner')
  const project = series(episode([shot('s1', 1, { productionMethod: 'animation_3d', attempts: [take('a1')] })]))
  useStore.setState({ activeWorkspace: 'plus-ultra', mediaFilter: 'world3d' })
  useSeriesStore.setState({ workspace: 'plus-ultra', activeSeriesId: project.id, activeEpisodeId: 'ep1', serverRevision: project.revision, hydrated: true, dirty: false,
    library: { schema: 'series-library', version: 1, workspaceId: 'plus-ultra', seriesOrder: [project.id], seriesById: { [project.id]: project } } })
  const openedAt = Date.now() - 60_000
  setShotEditSession({ workspace: 'plus-ultra', seriesId: 'mp-es', episodeId: 'ep1', shotId: 's1', order: 1, episodeTitle: 'La confesión',
    sceneFilename: 'mp-es-ep1-s1.world3d.scene.json', sceneName: 'mp-es-ep1-s1', dimension: '3d', productionMethod: 'animation_3d', openedAt })
  const calls: Array<{ method: string; path: string; body?: unknown }> = []
  const original = globalThis.fetch
  t.after(() => { cleanup(); globalThis.fetch = original; setShotEditSession(null) })
  globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input), path = url.replace(/^.*\/api\/v1/, '').split('?')[0]
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    calls.push({ method: init?.method || 'GET', path, body })
    if (path === '/outputs') return jsonResponse({ total: 2, outputs: [
      { name: 'old.mp4', type: 'video', mode: null, size: 1, created_at: (openedAt - 600_000) / 1000, url: '/api/v1/file/old.mp4' },
      { name: 'world3d-edit.mp4', type: 'video', mode: null, size: 1, created_at: (openedAt + 30_000) / 1000, url: '/api/v1/file/world3d-edit.mp4', thumbnail_url: '/thumb.jpg' },
    ] })
    if (path.startsWith('/file/')) return new Response(new Blob(['mp4']), { status: 200 })
    if (path === '/upload') return jsonResponse({ filename: 'world3d-edit.mp4', path: '/uploads/world3d-edit.mp4', url: '/api/v1/uploads/world3d-edit.mp4' })
    if (path.endsWith('/assets/import')) return jsonResponse({ asset: { id: 'asset-new' }, series: { ...project, revision: 8 } })
    throw new Error(`Unexpected request ${path}`)
  }) as typeof fetch
  const view = render(<SeriesShotEditBanner />)
  assert.ok(view.getByText(/Editing shot #1/))
  assert.equal(view.queryByRole('button', { name: "Export and use as the shot's take" }), null, 'the 3D editor has no export bridge')
  fireEvent.click(view.getByRole('button', { name: 'Choose a recent export' }))
  const choice = await view.findByRole('button', { name: 'Use world3d-edit.mp4' })
  assert.equal(view.queryByRole('button', { name: 'Use old.mp4' }), null, 'only exports made after the shot was opened')
  fireEvent.click(choice)
  await waitFor(() => assert.ok(calls.some(call => call.path.endsWith('/assets/import')), view.queryByRole('alert')?.textContent || JSON.stringify(calls.map(call => call.path))))
  const imported = calls.find(call => call.path.endsWith('/assets/import'))!
  assert.deepEqual(imported.body, { workspace: 'plus-ultra', uploadPath: '/uploads/world3d-edit.mp4', name: 'world3d-edit.mp4', ownerType: 'shot', ownerId: 's1',
    kind: 'video', asTake: true, metadata: { productionMethod: 'animation_3d', sceneFilename: 'mp-es-ep1-s1.world3d.scene.json', editedInEditor: true } })
  await waitFor(() => assert.equal(useShotEditSession.getState().session, null))
  assert.equal(useStore.getState().mediaFilter, 'series')
  assert.equal(useShotEditSession.getState().focusShotId, 's1')
  assert.equal(useSeriesStore.getState().library.seriesById['mp-es'].revision, 8)
})

test('opening a shot in the editor loads exactly its take\'s scene and remembers the shot', { concurrency: false }, async t => {
  const { render, cleanup } = await import('@testing-library/react')
  const { useStore } = await import('../src/stores/useStore')
  const { useSceneDocumentHandoff } = await import('../src/features/sceneFx/handoff')
  const { openShotInEditor, setShotEditSession, useShotEditSession } = await import('../src/features/series/shotEditSession')
  const ep = episode([shot('s1', 1, { attempts: [take('a1')] })])
  const project = series(ep)
  useStore.setState({ activeWorkspace: 'plus-ultra', mediaFilter: 'series' })
  const requested: string[] = []
  const original = globalThis.fetch
  t.after(() => { cleanup(); globalThis.fetch = original; setShotEditSession(null) })
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    requested.push(String(input))
    return new Response(JSON.stringify({ version: 1, name: 'mp-es-ep1-s1', width: 1920, height: 1080, duration: 2.5, fps: 30, layers: [{ id: 'bg', type: 'image', source: '/bg.png' }] }))
  }) as typeof fetch
  const received: unknown[] = []
  function Editor() { useSceneDocumentHandoff('2d', document => received.push(document)); return null }
  render(<Editor />)
  await openShotInEditor('plus-ultra', project, ep, ep.shots[0])
  assert.match(requested[0], /\/api\/v1\/file\/mp-es-ep1-s1\.scene\.json\?workspace=plus-ultra$/)
  assert.equal((received[0] as { name: string }).name, 'mp-es-ep1-s1')
  assert.equal(useStore.getState().mediaFilter, 'scene3d')
  const session = useShotEditSession.getState().session!
  assert.deepEqual({ shotId: session.shotId, sceneFilename: session.sceneFilename, sceneName: session.sceneName, dimension: session.dimension },
    { shotId: 's1', sceneFilename: 'mp-es-ep1-s1.scene.json', sceneName: 'mp-es-ep1-s1', dimension: '2d' })
  assert.match(sessionStorage.getItem('hocuspocus:series-shot-edit') || '', /"shotId":"s1"/, 'the session survives a reload of the tab')
})
