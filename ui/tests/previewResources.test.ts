import assert from 'node:assert/strict'
import { performance } from 'node:perf_hooks'
import test from 'node:test'
import type { PickerItem } from '../src/features/asset-picker/types.ts'
import {
  PREVIEW_BYTE_LIMIT,
  createPreviewResourcePool,
  listPreviewPlan,
  needsFullPreview,
  previewResourceKey,
  type PreviewFetcher,
  type PreviewRequest,
} from '../src/features/asset-picker/previewResources.ts'

function item(kind: PickerItem['kind'], name: string, workspace = 'film', sizeBytes = 12): PickerItem {
  return {
    ref: { version: 1, scheme: 'catalog', id: name, workspaceId: workspace, filename: name },
    kind,
    filename: name,
    title: name,
    createdAt: 1_700_000_000,
    sizeBytes,
    url: `/media/${workspace}/${name}`,
    thumbnailUrl: kind === 'image' ? `/media/${workspace}/${name}` : `/thumbs/${name}.png`,
  }
}

function fullRequest(entry: PickerItem): PreviewRequest {
  return {
    sourceUrl: entry.url,
    workspaceId: entry.ref.workspaceId,
    layer: 'full',
    mediaKind: entry.kind,
    sizeBytes: entry.sizeBytes,
    thumbnailUrl: entry.thumbnailUrl,
  }
}

function trackingPool(fetch: PreviewFetcher, maxCacheEntries = 4) {
  const created: string[] = []
  const revoked: string[] = []
  const pool = createPreviewResourcePool({
    maxCacheEntries,
    maxCacheBytes: 1024,
    copyRemote: true,
    fetch,
    createObjectURL: blob => {
      const url = `blob:preview:${created.length}:${blob.size}`
      created.push(url)
      return url
    },
    revokeObjectURL: url => { revoked.push(url) },
  })
  return { pool, created, revoked }
}

function instantFetch(body = 'asset'): PreviewFetcher {
  return async url => new Blob([`${body}:${url}`], { type: 'application/octet-stream' })
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
    release(url: string, body = 'asset') {
      const list = waiters.get(url) ?? []
      waiters.delete(url)
      for (const waiter of list) {
        if (!waiter.signal.aborted) waiter.resolve(new Blob([`${body}:${url}`]))
      }
    },
  }
}

test('list rows never schedule full GLB/audio/video loads', () => {
  const items = [
    item('model3d', 'hero.glb'),
    item('audio', 'line.wav'),
    item('video', 'take.mp4'),
    item('image', 'still.png'),
  ]
  const plan = listPreviewPlan(items)
  assert.equal(plan.items, 4)
  assert.equal(plan.fullLoads, 0)
  assert.equal(plan.modelViewerMounts, 0)
  assert.equal(plan.thumbnails, 4)
  assert.equal(needsFullPreview(items[0], false), false)
  assert.equal(needsFullPreview(items[0], true), true)
  assert.equal(needsFullPreview(items[3], true), false)
  assert.match(previewResourceKey(items[0], 'full'), /^full:catalog:hero.glb@film:hero.glb:/)
})

test('naive 20 open/close without revoke grows live object URLs; the pool does not', async () => {
  const created: string[] = []
  const naiveCreate = (blob: Blob) => {
    const url = `blob:naive:${created.length}:${blob.size}`
    created.push(url)
    return url
  }
  const started = performance.now()
  for (let index = 0; index < 20; index += 1) naiveCreate(new Blob([`glb-${index}`]))
  const naiveMs = performance.now() - started
  assert.equal(created.length, 20)

  const { pool, created: pooled, revoked } = trackingPool(instantFetch('glb'))
  const pooledStarted = performance.now()
  for (let index = 0; index < 20; index += 1) {
    const session = pool.createSession({ scope: 'picker' })
    const lease = await session.acquire(fullRequest(item('model3d', `hero-${index}.glb`)))
    assert.ok(lease?.objectUrl)
    session.dispose()
  }
  const pooledMs = performance.now() - pooledStarted
  const after = pool.snapshot()
  assert.equal(after.leasesLive, 0)
  assert.equal(after.refcountSum, 0)
  assert.equal(after.abortControllersLive, 0)
  assert.equal(after.inFlight, 0)
  assert.ok(after.objectUrlsLive <= 4, `expected bounded cache, got ${after.objectUrlsLive}`)
  assert.equal(after.objectUrlsLive, pooled.length - revoked.length)
  assert.equal(after.fullAcquires, 20)
  pool.dispose()
  assert.equal(pool.snapshot().objectUrlsLive, 0)
  assert.ok(naiveMs >= 0 && pooledMs >= 0)
})

test('20 open/close of the same GLB/audio/video keep a single cached buffer', async () => {
  const { pool } = trackingPool(instantFetch('media'), 8)
  const corpus = [item('model3d', 'hero.glb'), item('audio', 'line.wav'), item('video', 'take.mp4')]
  for (let cycle = 0; cycle < 20; cycle += 1) {
    for (const entry of corpus) {
      const session = pool.createSession({ scope: 'picker' })
      const lease = await session.acquire(fullRequest(entry))
      assert.ok(lease?.objectUrl)
      session.dispose()
    }
  }
  const after = pool.snapshot()
  assert.equal(after.leasesLive, 0)
  assert.equal(after.refcountSum, 0)
  assert.equal(after.abortControllersLive, 0)
  assert.equal(after.objectUrlsLive, 3)
  assert.equal(after.fullAcquires, 60)
  pool.dispose()
})

test('a late fetch after workspace/resource change is not published', async () => {
  const gate = gatedFetch()
  const { pool, created } = trackingPool(gate.fetch)
  const session = pool.createSession({ scope: 'picker' })
  const first = item('video', 'clip-a.mp4', 'alpha')
  const pending = session.acquire(fullRequest(first))
  assert.equal(pool.snapshot().inFlight, 1)
  const second = session.acquire(fullRequest(item('video', 'clip-b.mp4', 'beta')))
  assert.equal(gate.pending(first.url), 0)
  gate.release(first.url, 'stale')
  gate.release(item('video', 'clip-b.mp4', 'beta').url, 'fresh')
  assert.equal(await pending, null)
  const lease = await second
  assert.equal(lease?.playUrl, created[0])
  assert.equal(pool.snapshot().published, 1)
  assert.ok(pool.snapshot().staleDropped >= 1)
  assert.equal(created.length, 1)
  session.dispose()
  pool.dispose()
})

test('releasing the picker does not revoke a buffer still held by another view', async () => {
  const { pool, created, revoked } = trackingPool(instantFetch('shared'))
  const shared = item('audio', 'voice.wav')
  const picker = pool.createSession({ scope: 'picker' })
  const scene = pool.createSession({ scope: 'scene', exclusiveFull: false })
  const pickerLease = await picker.acquire(fullRequest(shared))
  const sceneLease = await scene.acquire(fullRequest(shared))
  assert.equal(pickerLease?.objectUrl, sceneLease?.objectUrl)
  assert.equal(pool.snapshot().refcountSum, 2)
  picker.dispose()
  assert.deepEqual(revoked, [])
  assert.equal(sceneLease?.playUrl, created[0])
  assert.equal(pool.snapshot().objectUrlsLive, 1)
  assert.equal(pool.snapshot().leasesLive, 1)
  scene.dispose()
  assert.equal(pool.snapshot().leasesLive, 0)
  pool.dispose()
})

test('thumbnail acquires do not copy the full remote body', async () => {
  let fetches = 0
  const { pool, created } = trackingPool(async url => {
    fetches += 1
    return new Blob([url])
  })
  const session = pool.createSession({ scope: 'picker' })
  const hero = item('model3d', 'hero.glb')
  const thumb = await session.acquire({
    sourceUrl: hero.url,
    workspaceId: hero.ref.workspaceId,
    layer: 'thumbnail',
    mediaKind: hero.kind,
    thumbnailUrl: hero.thumbnailUrl,
  })
  assert.equal(fetches, 0)
  assert.equal(created.length, 0)
  assert.equal(thumb?.objectUrl, null)
  assert.equal(thumb?.playUrl, hero.thumbnailUrl)
  session.dispose()
  pool.dispose()
})

test('files over the preview byte limit never start a copy fetch', async () => {
  let fetches = 0
  const { pool, created } = trackingPool(async url => {
    fetches += 1
    return new Blob([url])
  })
  const session = pool.createSession({ scope: 'picker' })
  const huge = item('video', 'huge.mp4', 'film', PREVIEW_BYTE_LIMIT + 1)
  const lease = await session.acquire(fullRequest(huge))
  assert.equal(fetches, 0)
  assert.equal(created.length, 0)
  assert.equal(lease?.playUrl, huge.url)
  session.dispose()
  pool.dispose()
})

test('inline blob URLs are leased without revoking a foreign object URL', async () => {
  const foreign = 'blob:scene-already-playing'
  const { pool, created, revoked } = trackingPool(instantFetch('nope'))
  const session = pool.createSession({ scope: 'picker' })
  const lease = await session.acquire({
    sourceUrl: foreign,
    workspaceId: 'film',
    layer: 'full',
    mediaKind: 'audio',
    sizeBytes: 8,
  })
  assert.equal(lease?.playUrl, foreign)
  assert.equal(lease?.objectUrl, null)
  assert.deepEqual(created, [])
  session.dispose()
  assert.deepEqual(revoked, [])
  pool.dispose()
})

test('a picker session only keeps one full preview armed at a time', async () => {
  const { pool } = trackingPool(instantFetch('one'))
  const session = pool.createSession({ scope: 'picker' })
  const first = await session.acquire(fullRequest(item('video', 'a.mp4')))
  const second = await session.acquire(fullRequest(item('video', 'b.mp4')))
  assert.ok(first)
  assert.ok(second)
  assert.equal(pool.snapshot().leasesLive, 1)
  assert.equal(pool.snapshot().refcountSum, 1)
  session.dispose()
  pool.dispose()
})
