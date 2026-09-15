import assert from 'node:assert/strict'
import test from 'node:test'
import React from 'react'
import { JSDOM } from 'jsdom'
import type { PickerItem } from '../src/features/asset-picker/types.ts'
import {
  createPreviewResourcePool,
  resetSharedPreviewPoolForTests,
  type PreviewFetcher,
  type PreviewResourcePool,
} from '../src/features/asset-picker/previewResources.ts'

Object.assign(globalThis, { React })

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  HTMLButtonElement: dom.window.HTMLButtonElement,
  HTMLMediaElement: dom.window.HTMLMediaElement,
  HTMLVideoElement: dom.window.HTMLVideoElement,
  HTMLAudioElement: dom.window.HTMLAudioElement,
  Event: dom.window.Event,
  MouseEvent: dom.window.MouseEvent,
  MutationObserver: dom.window.MutationObserver,
  ResizeObserver: class { observe() {} disconnect() {} },
})
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: dom.window.navigator })
if (globalThis.HTMLMediaElement?.prototype) {
  globalThis.HTMLMediaElement.prototype.pause = function pause() {}
  globalThis.HTMLMediaElement.prototype.load = function load() {}
}

function mediaItem(kind: PickerItem['kind'], name: string, workspace = 'film'): PickerItem {
  return {
    ref: { version: 1, scheme: 'catalog', id: name, workspaceId: workspace, filename: name },
    kind,
    filename: name,
    title: name,
    createdAt: 1_700_000_000,
    sizeBytes: 16,
    url: `/media/${workspace}/${name}`,
    thumbnailUrl: `/thumbs/${name}.png`,
  }
}

function trackingPool(fetch: PreviewFetcher) {
  const created: string[] = []
  const revoked: string[] = []
  const pool = createPreviewResourcePool({
    maxCacheEntries: 4,
    maxCacheBytes: 2048,
    copyRemote: true,
    fetch,
    createObjectURL: blob => {
      const url = `blob:player:${created.length}:${blob.size}`
      created.push(url)
      return url
    },
    revokeObjectURL: url => { revoked.push(url) },
  })
  return { pool, created, revoked }
}

function gatedFetch() {
  const waiters = new Map<string, { resolve: (blob: Blob) => void, reject: (error: Error) => void, signal: AbortSignal }[]>()
  const fetch: PreviewFetcher = (url, signal) => new Promise((resolve, reject) => {
    const fail = () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' }))
    if (signal.aborted) { fail(); return }
    const list = waiters.get(url) ?? []
    const entry = { resolve, reject, signal }
    list.push(entry)
    waiters.set(url, list)
    signal.addEventListener('abort', () => {
      const remaining = (waiters.get(url) ?? []).filter(item => item !== entry)
      if (remaining.length) waiters.set(url, remaining)
      else waiters.delete(url)
      fail()
    })
  })
  return {
    fetch,
    pending(url: string) { return waiters.get(url)?.length ?? 0 },
    release(url: string) {
      const list = waiters.get(url) ?? []
      waiters.delete(url)
      for (const waiter of list) {
        if (!waiter.signal.aborted) waiter.resolve(new Blob([url]))
      }
    },
  }
}

async function mountPlayer(item: PickerItem, pool: PreviewResourcePool) {
  const testing = await import('@testing-library/react')
  const { AssetPreviewPlayer } = await import('../src/features/asset-picker/previewPlayer.tsx')
  const view = testing.render(React.createElement(AssetPreviewPlayer, { item, pool }))
  return { ...testing, view, AssetPreviewPlayer }
}

test('unarmed preview does not copy remote media', { concurrency: false }, async () => {
  let fetches = 0
  const { pool } = trackingPool(async url => {
    fetches += 1
    return new Blob([url])
  })
  const { view, cleanup } = await mountPlayer(mediaItem('video', 'clip.mp4'), pool)
  try {
    assert.equal(view.queryByTestId('asset-preview-video'), null)
    assert.ok(view.getByTestId('asset-preview-arm'))
    assert.equal(fetches, 0)
    assert.equal(pool.snapshot().fullAcquires, 0)
  } finally {
    cleanup()
    pool.dispose()
    resetSharedPreviewPoolForTests()
  }
})

test('20 open/close cycles leave picker counters bounded and idle', { concurrency: false }, async () => {
  const { pool, created, revoked } = trackingPool(async url => new Blob([url]))
  const paused: string[] = []
  const proto = globalThis.HTMLMediaElement?.prototype
  const originalPause = proto?.pause
  const originalLoad = proto?.load
  if (proto) {
    proto.pause = function pause() { paused.push(this.getAttribute('src') || this.src || 'paused') }
    proto.load = function load() {}
  }
  const { render, fireEvent, screen, waitFor, cleanup } = await import('@testing-library/react')
  const { AssetPreviewPlayer } = await import('../src/features/asset-picker/previewPlayer.tsx')
  try {
    for (let index = 0; index < 20; index += 1) {
      const entry = mediaItem(index % 2 ? 'audio' : 'video', `clip-${index}.${index % 2 ? 'wav' : 'mp4'}`)
      const view = render(React.createElement(AssetPreviewPlayer, { item: entry, pool }))
      fireEvent.click(screen.getByTestId('asset-preview-arm'))
      await waitFor(() => assert.equal(pool.snapshot().leasesLive, 1))
      view.unmount()
    }
    const after = pool.snapshot()
    assert.equal(after.leasesLive, 0)
    assert.equal(after.refcountSum, 0)
    assert.equal(after.abortControllersLive, 0)
    assert.equal(after.inFlight, 0)
    assert.ok(after.objectUrlsLive <= 4)
    assert.equal(after.objectUrlsLive, created.length - revoked.length)
    assert.equal(after.fullAcquires, 20)
    assert.ok(paused.length >= 20)
  } finally {
    if (proto && originalPause) proto.pause = originalPause
    if (proto && originalLoad) proto.load = originalLoad
    cleanup()
    pool.dispose()
    resetSharedPreviewPoolForTests()
  }
})

test('switching the selected asset during a download does not publish the previous blob', { concurrency: false }, async () => {
  const gate = gatedFetch()
  const { pool, created } = trackingPool(gate.fetch)
  const first = mediaItem('video', 'clip-a.mp4', 'alpha')
  const second = mediaItem('video', 'clip-b.mp4', 'beta')
  const { view, fireEvent, screen, waitFor, cleanup, AssetPreviewPlayer } = await mountPlayer(first, pool)
  const paused: string[] = []
  const proto = globalThis.HTMLMediaElement?.prototype
  const originalPause = proto?.pause
  const originalLoad = proto?.load
  if (proto) {
    proto.pause = function pause() { paused.push('paused') }
    proto.load = function load() {}
  }
  try {
    fireEvent.click(screen.getByTestId('asset-preview-arm'))
    await waitFor(() => assert.equal(gate.pending(first.url), 1))
    view.rerender(React.createElement(AssetPreviewPlayer, { item: second, pool }))
    gate.release(first.url)
    await waitFor(() => assert.equal(pool.snapshot().inFlight, 0))
    assert.equal(screen.queryByTestId('asset-preview-video'), null)
    assert.ok(screen.getByTestId('asset-preview-arm'))
    assert.deepEqual(created, [])
    fireEvent.click(screen.getByTestId('asset-preview-arm'))
    gate.release(second.url)
    await waitFor(() => assert.equal(pool.snapshot().leasesLive, 1))
    const video = screen.getByTestId('asset-preview-video')
    assert.equal(video.getAttribute('data-preview-src'), created[0])
    assert.ok(paused.length >= 1)
    assert.equal(pool.snapshot().published, 1)
  } finally {
    if (proto && originalPause) proto.pause = originalPause
    if (proto && originalLoad) proto.load = originalLoad
    cleanup()
    pool.dispose()
    resetSharedPreviewPoolForTests()
  }
})

test('closing the player releases only the picker lease', { concurrency: false }, async () => {
  const { pool, created, revoked } = trackingPool(async url => new Blob([url]))
  const shared = mediaItem('audio', 'voice.wav')
  const scene = pool.createSession({ scope: 'scene', exclusiveFull: false })
  const sceneLease = await scene.acquire({
    sourceUrl: shared.url,
    workspaceId: shared.ref.workspaceId,
    layer: 'full',
    mediaKind: shared.kind,
    sizeBytes: shared.sizeBytes,
  })
  const { view, fireEvent, screen, waitFor, cleanup } = await mountPlayer(shared, pool)
  try {
    fireEvent.click(screen.getByTestId('asset-preview-arm'))
    await waitFor(() => assert.equal(pool.snapshot().leasesLive, 2))
    cleanup()
    assert.equal(pool.snapshot().leasesLive, 1)
    assert.deepEqual(revoked, [])
    assert.equal(sceneLease?.playUrl, created[0])
    scene.dispose()
    assert.equal(pool.snapshot().leasesLive, 0)
  } finally {
    view.unmount()
    pool.dispose()
    resetSharedPreviewPoolForTests()
  }
})
