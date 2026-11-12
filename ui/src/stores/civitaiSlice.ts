import * as api from '../api/client'
import type { CivitAIDownload, CivitAIModel, GenerateParams } from '../types'
import type { SliceCreator } from './storeApi'

const CIVIT_DOWNLOAD_POLL_MS = 2000
const CIVIT_DOWNLOAD_COMPLETED_VISIBLE_MS = 30_000
let _civitDownloadPollTask: Promise<void> | null = null
let _civitDownloadPollController: AbortController | null = null
let _civitDownloadPollRequested = false
const _civitRefreshedCheckpointDownloads = new Set<string>()

export function _downloadTimestampMs(value: number | null | undefined): number | null {
  const timestamp = Number(value)
  if (!Number.isFinite(timestamp) || timestamp <= 0) return null
  return timestamp < 1_000_000_000_000 ? timestamp * 1000 : timestamp
}

function _downloadNeedsPolling(download: CivitAIDownload, now: number): boolean {
  if (download.status === 'downloading') return true
  if (download.status !== 'completed') return false
  const completedAt = _downloadTimestampMs(download.completed_at)
  return completedAt !== null && now - completedAt < CIVIT_DOWNLOAD_COMPLETED_VISIBLE_MS
}

function _waitForDownloadPoll(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise(resolve => {
    if (signal.aborted) {
      resolve()
      return
    }
    const timer = window.setTimeout(done, ms)
    function done() {
      window.clearTimeout(timer)
      signal.removeEventListener('abort', done)
      resolve()
    }
    signal.addEventListener('abort', done, { once: true })
  })
}

export function disposeCivitaiDownloadPoll(): void {
  _civitDownloadPollController?.abort()
  _civitDownloadPollController = null
  _civitDownloadPollTask = null
  _civitDownloadPollRequested = false
  _civitRefreshedCheckpointDownloads.clear()
}

export type CivitaiSlice = {
  // CivitAI LoRA Browser
  loraBrowserOpen: boolean
  loraBrowserArch: string | null
  loraBrowserDefaultDir: string | null
  setLoraBrowserOpen: (open: boolean, arch?: string) => void
  setLoraBrowserDefaultDir: (dir: string | null) => void
  civitSearchResults: CivitAIModel[]
  civitSearchCursor: string | null
  civitSearchLoading: boolean
  civitSearchError: string | null
  civitSelectedModel: CivitAIModel | null
  civitDownloads: CivitAIDownload[]
  searchCivitAI: (params: Record<string, unknown>, append?: boolean) => Promise<void>
  selectCivitAIModel: (modelId: number) => Promise<void>
  clearCivitSelection: () => void
  startCivitAIDownload: (params: Record<string, unknown>) => Promise<void>
  pollCivitAIDownloads: () => void
}

export type CivitaiSliceHost = CivitaiSlice & {
  loadModels: () => Promise<void>
  loadLoras: (modelType: string) => Promise<void>
  params: GenerateParams
}

export const createCivitaiSlice: SliceCreator<CivitaiSlice, CivitaiSliceHost> = (set, get) => ({
  // CivitAI LoRA Browser
  loraBrowserOpen: false,
  loraBrowserArch: null,
  loraBrowserDefaultDir: null,
  setLoraBrowserDefaultDir: (dir) => set({ loraBrowserDefaultDir: dir }),
  setLoraBrowserOpen: (open, arch) => {
    if (open) {
      set({ loraBrowserOpen: true, loraBrowserArch: arch || null, civitSearchResults: [], civitSearchCursor: null, civitSelectedModel: null })
      // Adopt downloads started by URL imports, recipes, or another browser
      // session instead of assuming this store initiated every transfer.
      get().pollCivitAIDownloads()
    } else {
      set({ loraBrowserOpen: false })
      // Refresh LoRA list after closing (may have downloaded new ones)
      const modelType = get().params.model_type
      if (modelType) get().loadLoras(modelType)
    }
  },
  civitSearchResults: [],
  civitSearchCursor: null,
  civitSearchLoading: false,
  civitSearchError: null,
  civitSelectedModel: null,
  civitDownloads: [],

  searchCivitAI: async (params, append = false) => {
    set({ civitSearchLoading: true, civitSearchError: null })
    try {
      const result = await api.searchCivitAI(params as Parameters<typeof api.searchCivitAI>[0])
      if (append) {
        set(s => ({
          civitSearchResults: [...s.civitSearchResults, ...result.items],
          civitSearchCursor: result.metadata?.nextCursor || null,
          civitSearchLoading: false,
        }))
      } else {
        set({
          civitSearchResults: result.items,
          civitSearchCursor: result.metadata?.nextCursor || null,
          civitSearchLoading: false,
          civitSelectedModel: null,
        })
      }
    } catch (e) {
      console.error('CivitAI search failed:', e)
      const msg = e instanceof Error ? e.message : 'CivitAI search failed'
      set({ civitSearchLoading: false, civitSearchError: msg })
    }
  },

  selectCivitAIModel: async (modelId) => {
    try {
      const model = await api.fetchCivitAIModel(modelId)
      set({ civitSelectedModel: model })
    } catch (e) {
      console.error('Failed to fetch model details:', e)
    }
  },

  clearCivitSelection: () => set({ civitSelectedModel: null }),

  startCivitAIDownload: async (params) => {
    try {
      await api.startCivitAIDownload(params as Parameters<typeof api.startCivitAIDownload>[0])
      get().pollCivitAIDownloads()
    } catch (e) {
      console.error('Download failed:', e)
    }
  },

  pollCivitAIDownloads: () => {
    // Mark every invocation, including calls made while the singleton loop is
    // awaiting an older request. The active loop consumes this before exit
    // and takes a new snapshot that was initiated after the caller arrived.
    _civitDownloadPollRequested = true
    if (_civitDownloadPollTask) return

    const controller = new AbortController()
    _civitDownloadPollController = controller
    const poll = async () => {
      let consecutiveErrors = 0
      try {
        while (!controller.signal.aborted) {
          _civitDownloadPollRequested = false
          try {
            const { downloads } = await api.fetchCivitAIDownloads()
            consecutiveErrors = 0
            set({ civitDownloads: downloads })

            // Checkpoint downloads are registered on the server before their
            // terminal record is published. Refresh here, in the singleton
            // poller, so navigating away from ModelDetail cannot skip it and
            // a Content-Disposition filename change cannot break matching.
            const completedCheckpoints = downloads.filter(download =>
              download.status === 'completed'
              && !!download.model_type
              && !_civitRefreshedCheckpointDownloads.has(download.id)
            )
            if (completedCheckpoints.length > 0) {
              try {
                await api.reloadModels()
                await get().loadModels()
                completedCheckpoints.forEach(download => {
                  _civitRefreshedCheckpointDownloads.add(download.id)
                })
              } catch (error) {
                // Keep the IDs unmarked so a later poll retries the refresh.
                console.warn('Checkpoint model refresh failed; will retry:', error)
              }
            }

            // A caller joined while this request was in flight. Its freshness
            // guarantee requires another request, even when this response has
            // no active/recent downloads and would normally end the loop.
            if (_civitDownloadPollRequested) continue

            // Keep taking snapshots while work is active and through the
            // completed row's 30-second display window. This guarantees a
            // caller that joins late still observes the terminal record.
            if (!downloads.some(download => _downloadNeedsPolling(download, Date.now()))) return
            await _waitForDownloadPoll(CIVIT_DOWNLOAD_POLL_MS, controller.signal)
          } catch (error) {
            if (controller.signal.aborted) return
            consecutiveErrors += 1
            if (_civitDownloadPollRequested) continue
            const knownWork = get().civitDownloads.some(download =>
              _downloadNeedsPolling(download, Date.now())
            )
            // Retry transient failures while the browser is open or known
            // work is active. A background adoption probe gets three retries
            // before yielding; a later caller can safely start a fresh loop.
            if (!get().loraBrowserOpen && !knownWork && consecutiveErrors > 3) {
              console.warn('Download polling paused after repeated errors:', error)
              return
            }
            const retryMs = Math.min(10_000, 1000 * (2 ** Math.min(consecutiveErrors - 1, 3)))
            await _waitForDownloadPoll(retryMs, controller.signal)
          }
        }
      } finally {
        if (_civitDownloadPollController === controller) {
          _civitDownloadPollController = null
          _civitDownloadPollTask = null
        }
      }
    }

    _civitDownloadPollTask = poll()
  },
})
