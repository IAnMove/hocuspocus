import { assetRefKey, type PickerItem } from './types.ts'

export const PREVIEW_BYTE_LIMIT = 80 * 1024 * 1024
export const PREVIEW_CACHE_LIMIT = 8
export const PREVIEW_CACHE_BYTES = 32 * 1024 * 1024

export type PreviewLayer = 'thumbnail' | 'full'
export type PreviewScope = 'picker' | 'scene' | 'panel'

export type PreviewRequest = {
  sourceUrl: string
  workspaceId: string
  layer: PreviewLayer
  mediaKind: PickerItem['kind']
  sizeBytes?: number
  thumbnailUrl?: string
}

export type PreviewLease = {
  ownerId: string
  key: string
  playUrl: string
  objectUrl: string | null
  generation: number
  fromCache: boolean
  release: () => void
}

export type PreviewCounters = {
  objectUrlsLive: number
  objectUrlsCreated: number
  objectUrlsRevoked: number
  abortControllersLive: number
  abortControllersCreated: number
  leasesLive: number
  refcountSum: number
  cacheEntries: number
  cacheBytes: number
  inFlight: number
  published: number
  staleDropped: number
  fullAcquires: number
  thumbnailAcquires: number
}

export type PreviewFetcher = (url: string, signal: AbortSignal) => Promise<Blob>

export type PreviewPoolOptions = {
  maxCacheEntries?: number
  maxCacheBytes?: number
  copyRemote?: boolean
  fetch?: PreviewFetcher
  createObjectURL?: (blob: Blob) => string
  revokeObjectURL?: (url: string) => void
  now?: () => number
}

type CacheEntry = {
  key: string
  playUrl: string
  objectUrl: string | null
  bytes: number
  refcount: number
  lastUsed: number
  createdByPool: boolean
}

type Waiter = {
  ownerId: string
  isCurrent: () => boolean
  resolve: (entry: CacheEntry | null) => void
}

type Flight = {
  controller: AbortController
  waiters: Waiter[]
}

function emptyCounters(): PreviewCounters {
  return {
    objectUrlsLive: 0,
    objectUrlsCreated: 0,
    objectUrlsRevoked: 0,
    abortControllersLive: 0,
    abortControllersCreated: 0,
    leasesLive: 0,
    refcountSum: 0,
    cacheEntries: 0,
    cacheBytes: 0,
    inFlight: 0,
    published: 0,
    staleDropped: 0,
    fullAcquires: 0,
    thumbnailAcquires: 0,
  }
}

export function previewResourceKey(
  item: Pick<PickerItem, 'ref' | 'url'>,
  layer: PreviewLayer,
): string {
  return `${layer}:${assetRefKey(item.ref)}:${item.url}`
}

export function previewRequestKey(request: PreviewRequest): string {
  return `${request.layer}:${request.workspaceId}:${request.sourceUrl}`
}

export function isInlinePreviewUrl(url: string): boolean {
  return url.startsWith('blob:') || url.startsWith('data:')
}

export function needsFullPreview(item: Pick<PickerItem, 'kind'>, armed: boolean): boolean {
  if (!armed) return false
  return item.kind === 'video' || item.kind === 'audio' || item.kind === 'model3d'
}

/** Gallery rows never start a full GLB/audio/video load. */
export function listPreviewPlan(items: readonly PickerItem[]) {
  const thumbnailUrls = items.map(item => item.thumbnailUrl).filter(Boolean)
  return {
    items: items.length,
    thumbnails: thumbnailUrls.length,
    thumbnailUrls,
    fullLoads: 0,
    modelViewerMounts: 0,
  }
}

function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === 'object' && 'name' in error && (error as { name: string }).name === 'AbortError')
}

export type PreviewSession = {
  readonly ownerId: string
  readonly scope: PreviewScope
  readonly generation: number
  acquire: (request: PreviewRequest) => Promise<PreviewLease | null>
  cancelCurrent: () => void
  dispose: () => void
}

export type PreviewResourcePool = {
  createSession: (input: { scope: PreviewScope; ownerId?: string; exclusiveFull?: boolean }) => PreviewSession
  snapshot: () => PreviewCounters
  dispose: () => void
}

export function createPreviewResourcePool(options: PreviewPoolOptions = {}): PreviewResourcePool {
  const maxCacheEntries = options.maxCacheEntries ?? PREVIEW_CACHE_LIMIT
  const maxCacheBytes = options.maxCacheBytes ?? PREVIEW_CACHE_BYTES
  const copyRemote = options.copyRemote ?? Boolean(options.fetch)
  const fetchBlob = options.fetch ?? defaultPreviewFetch
  const createObjectURL = options.createObjectURL ?? ((blob: Blob) => URL.createObjectURL(blob))
  const revokeObjectURL = options.revokeObjectURL ?? ((url: string) => URL.revokeObjectURL(url))
  const now = options.now ?? (() => Date.now())

  const counters = emptyCounters()
  const entries = new Map<string, CacheEntry>()
  const flights = new Map<string, Flight>()
  let ownerSeq = 0
  let disposed = false

  function snapshot(): PreviewCounters {
    let refcountSum = 0
    let cacheBytes = 0
    let cacheEntries = 0
    for (const entry of entries.values()) {
      refcountSum += entry.refcount
      cacheEntries += 1
      cacheBytes += entry.bytes
    }
    return {
      ...counters,
      refcountSum,
      cacheEntries,
      cacheBytes,
      inFlight: flights.size,
    }
  }

  function dropCreatedUrl(entry: CacheEntry) {
    if (!entry.createdByPool || !entry.objectUrl) return
    revokeObjectURL(entry.objectUrl)
    counters.objectUrlsRevoked += 1
    counters.objectUrlsLive = Math.max(0, counters.objectUrlsLive - 1)
    entry.objectUrl = null
    entry.bytes = 0
    entry.createdByPool = false
  }

  function evictIdle() {
    const idle = [...entries.values()]
      .filter(entry => entry.refcount === 0 && entry.createdByPool)
      .sort((left, right) => left.lastUsed - right.lastUsed)
    const over = () => {
      const live = [...entries.values()].filter(entry => entry.createdByPool).length
      const bytes = [...entries.values()].reduce((sum, entry) => sum + entry.bytes, 0)
      return live > maxCacheEntries || bytes > maxCacheBytes
    }
    while (idle.length && over()) {
      const victim = idle.shift()
      if (!victim) break
      dropCreatedUrl(victim)
      entries.delete(victim.key)
    }
  }

  function rememberSource(key: string, playUrl: string): CacheEntry {
    const existing = entries.get(key)
    if (existing) {
      existing.lastUsed = now()
      return existing
    }
    const entry: CacheEntry = {
      key,
      playUrl,
      objectUrl: null,
      bytes: 0,
      refcount: 0,
      lastUsed: now(),
      createdByPool: false,
    }
    entries.set(key, entry)
    return entry
  }

  function materialize(key: string, blob: Blob): CacheEntry {
    const existing = entries.get(key)
    if (existing?.objectUrl && existing.createdByPool) {
      existing.lastUsed = now()
      return existing
    }
    const objectUrl = createObjectURL(blob)
    counters.objectUrlsCreated += 1
    counters.objectUrlsLive += 1
    const entry: CacheEntry = {
      key,
      playUrl: objectUrl,
      objectUrl,
      bytes: blob.size,
      refcount: existing?.refcount ?? 0,
      lastUsed: now(),
      createdByPool: true,
    }
    entries.set(key, entry)
    evictIdle()
    return entry
  }

  function retain(ownerId: string, entry: CacheEntry, generation: number, fromCache: boolean): PreviewLease {
    entry.refcount += 1
    entry.lastUsed = now()
    counters.leasesLive += 1
    let released = false
    const lease: PreviewLease = {
      ownerId,
      key: entry.key,
      playUrl: entry.playUrl,
      objectUrl: entry.objectUrl,
      generation,
      fromCache,
      release() {
        if (released) return
        released = true
        counters.leasesLive = Math.max(0, counters.leasesLive - 1)
        entry.refcount = Math.max(0, entry.refcount - 1)
        entry.lastUsed = now()
        if (entry.refcount === 0 && !entry.createdByPool) entries.delete(entry.key)
        else evictIdle()
      },
    }
    return lease
  }

  function cancelOwnerWaiters(ownerId: string) {
    for (const [key, flight] of [...flights.entries()]) {
      const kept: Waiter[] = []
      for (const waiter of flight.waiters) {
        if (waiter.ownerId === ownerId) {
          counters.staleDropped += 1
          waiter.resolve(null)
        } else kept.push(waiter)
      }
      flight.waiters = kept
      if (!kept.length) {
        flights.delete(key)
        counters.abortControllersLive = Math.max(0, counters.abortControllersLive - 1)
        flight.controller.abort()
      }
    }
  }

  function shouldCopy(request: PreviewRequest): boolean {
    if (request.layer !== 'full') return false
    if ((request.sizeBytes ?? 0) > PREVIEW_BYTE_LIMIT) return false
    if (isInlinePreviewUrl(request.sourceUrl)) return false
    return copyRemote
  }

  function settleFlight(flight: Flight, live: Waiter[], makeEntry: (() => CacheEntry) | null) {
    const stale = flight.waiters.length - live.length
    if (stale) counters.staleDropped += stale
    for (const waiter of flight.waiters) {
      if (!live.includes(waiter)) waiter.resolve(null)
    }
    if (!live.length || !makeEntry) return
    const entry = makeEntry()
    for (const waiter of live) waiter.resolve(entry)
  }

  function joinFlight(key: string, waiter: Waiter) {
    const flight = flights.get(key)
    if (!flight) return false
    flight.waiters.push(waiter)
    return true
  }

  function startFlight(request: PreviewRequest, key: string, waiter: Waiter) {
    const controller = new AbortController()
    counters.abortControllersCreated += 1
    counters.abortControllersLive += 1
    const flight: Flight = { controller, waiters: [waiter] }
    flights.set(key, flight)
    void fetchBlob(request.sourceUrl, controller.signal).then(blob => {
      const current = flights.get(key)
      if (current !== flight) return
      flights.delete(key)
      counters.abortControllersLive = Math.max(0, counters.abortControllersLive - 1)
      settleFlight(flight, flight.waiters.filter(item => item.isCurrent()), () => materialize(key, blob))
    }).catch((error: unknown) => {
      const current = flights.get(key)
      if (current !== flight) return
      flights.delete(key)
      counters.abortControllersLive = Math.max(0, counters.abortControllersLive - 1)
      if (isAbortError(error) || controller.signal.aborted) {
        settleFlight(flight, [], null)
        return
      }
      settleFlight(flight, flight.waiters.filter(item => item.isCurrent()), () => rememberSource(key, request.sourceUrl))
    })
  }

  function loadEntry(request: PreviewRequest, ownerId: string, isCurrent: () => boolean): Promise<CacheEntry | null> {
    const key = previewRequestKey(request)
    if (request.layer === 'thumbnail') {
      return Promise.resolve(rememberSource(key, request.thumbnailUrl || request.sourceUrl))
    }
    const cached = entries.get(key)
    if (cached?.createdByPool && cached.objectUrl) return Promise.resolve(cached)
    if (isInlinePreviewUrl(request.sourceUrl) || !shouldCopy(request)) {
      return Promise.resolve(rememberSource(key, request.sourceUrl))
    }
    return new Promise(resolve => {
      const waiter: Waiter = { ownerId, isCurrent, resolve }
      if (!joinFlight(key, waiter)) startFlight(request, key, waiter)
    })
  }

  function createSession(input: { scope: PreviewScope; ownerId?: string; exclusiveFull?: boolean }): PreviewSession {
    const ownerId = input.ownerId ?? `${input.scope}:${++ownerSeq}`
    const exclusiveFull = input.exclusiveFull ?? input.scope === 'picker'
    let generation = 0
    let sessionDisposed = false
    const held = new Set<PreviewLease>()
    let fullLease: PreviewLease | null = null

    function dropLease(lease: PreviewLease | null) {
      if (!lease) return
      held.delete(lease)
      if (fullLease === lease) fullLease = null
      lease.release()
    }

    const session: PreviewSession = {
      ownerId,
      scope: input.scope,
      get generation() { return generation },
      async acquire(request: PreviewRequest) {
        if (disposed || sessionDisposed) return null
        generation += 1
        const mine = generation
        if (request.layer === 'full') counters.fullAcquires += 1
        else counters.thumbnailAcquires += 1
        if (exclusiveFull && request.layer === 'full') {
          dropLease(fullLease)
          cancelOwnerWaiters(ownerId)
        }
        const entry = await loadEntry(request, ownerId, () => !disposed && !sessionDisposed && generation === mine)
        if (!entry || disposed || sessionDisposed || generation !== mine) {
          if (entry) counters.staleDropped += 1
          return null
        }
        const lease = retain(ownerId, entry, mine, Boolean(entry.createdByPool && entry.objectUrl))
        held.add(lease)
        if (request.layer === 'full') fullLease = lease
        counters.published += 1
        return lease
      },
      cancelCurrent() {
        generation += 1
        dropLease(fullLease)
        cancelOwnerWaiters(ownerId)
      },
      dispose() {
        if (sessionDisposed) return
        sessionDisposed = true
        generation += 1
        cancelOwnerWaiters(ownerId)
        for (const lease of [...held]) dropLease(lease)
        fullLease = null
      },
    }
    return session
  }

  return {
    createSession,
    snapshot,
    dispose() {
      disposed = true
      for (const flight of flights.values()) {
        for (const waiter of flight.waiters) waiter.resolve(null)
        flight.controller.abort()
      }
      flights.clear()
      counters.abortControllersLive = 0
      for (const entry of [...entries.values()]) {
        if (entry.createdByPool) dropCreatedUrl(entry)
      }
      entries.clear()
    },
  }
}

async function defaultPreviewFetch(url: string, signal: AbortSignal): Promise<Blob> {
  const response = await fetch(url, { signal })
  if (!response.ok) throw new Error(`preview fetch failed: ${response.status}`)
  return response.blob()
}

let sharedPool: PreviewResourcePool | null = null

export function getSharedPreviewPool(): PreviewResourcePool {
  sharedPool ??= createPreviewResourcePool({ copyRemote: false })
  return sharedPool
}

export function resetSharedPreviewPoolForTests() {
  sharedPool?.dispose()
  sharedPool = null
}
