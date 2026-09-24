import * as api from '../api/client'
import { GALLERY_LIST_FILTERS, galleryListQuery } from '../lib/galleryListQuery'
import type { MediaFilter, OutputFile, OutputMetadata } from '../types'
import type { SliceCreator } from './storeApi'

export type GalleryView = 'feed' | 'grid' | 'masonry'

const GALLERY_VIEW_KEY = 'hocuspocus_gallery_view'
const GALLERY_VIEWS: readonly GalleryView[] = ['feed', 'grid', 'masonry']

const GALLERY_GRID_COLUMNS_KEY = 'hocuspocus_gallery_grid_columns'
const GALLERY_ORDER_KEY = 'hocuspocus_gallery_order'
const GALLERY_ORDERS: readonly api.GalleryOrder[] = ['newest', 'oldest', 'favorites']

function readStoredGalleryOrder(): api.GalleryOrder {
  try {
    const stored = localStorage.getItem(GALLERY_ORDER_KEY)
    return GALLERY_ORDERS.includes(stored as api.GalleryOrder) ? stored as api.GalleryOrder : 'newest'
  } catch {
    return 'newest'
  }
}
export const GALLERY_GRID_COLUMN_RANGE = [2, 6] as const

function readStoredGridColumns(): number | null {
  try {
    const stored = Number(localStorage.getItem(GALLERY_GRID_COLUMNS_KEY))
    return Number.isInteger(stored) && stored >= GALLERY_GRID_COLUMN_RANGE[0] && stored <= GALLERY_GRID_COLUMN_RANGE[1] ? stored : null
  } catch {
    return null
  }
}

function readStoredGalleryView(): GalleryView {
  try {
    const stored = localStorage.getItem(GALLERY_VIEW_KEY)
    return GALLERY_VIEWS.includes(stored as GalleryView) ? stored as GalleryView : 'feed'
  } catch {
    return 'feed'
  }
}

export type GallerySlice = {
  workspaces: Array<{ name: string; path: string; file_count?: number }>
  activeWorkspace: string
  browsingUploads: boolean
  loadWorkspaces: () => Promise<void>
  switchWorkspace: (name: string) => Promise<void>
  createWorkspace: (name: string) => Promise<void>
  deleteWorkspace: (name: string) => Promise<void>
  outputs: OutputFile[]
  outputsTotal: number
  selectedOutput: number
  setSelectedOutput: (i: number) => void
  mediaFilter: MediaFilter
  /** How the gallery lays its items out. A preference, not state derived
   *  from the data: the same set of outputs is worth browsing densely one
   *  moment and reviewing one-up the next. */
  galleryView: GalleryView
  setGalleryView: (view: GalleryView) => void
  /** Phone grid columns chosen with a pinch; null follows the screen width. */
  galleryGridColumns: number | null
  setGalleryGridColumns: (columns: number | null) => void
  /** Listing order, applied by the server so paging follows it. */
  galleryOrder: api.GalleryOrder
  setGalleryOrder: (order: api.GalleryOrder) => void
  /** The phone history panel, opened from the gallery toolbar. */
  mobileHistoryOpen: boolean
  setMobileHistoryOpen: (open: boolean) => void
  outputSearchQuery: string
  galleryFeedAtTop: boolean
  galleryRefreshPending: boolean
  galleryToast: { id: number; message: string } | null
  setMediaFilter: (f: MediaFilter) => void
  setOutputSearchQuery: (q: string) => void
  setGalleryFeedAtTop: (atTop: boolean) => void
  clearGalleryToast: () => void
  maybeRefreshGallery: (opts?: { message?: string; force?: boolean }) => Promise<void>
  filteredOutputs: () => OutputFile[]
  outputsLoading: boolean
  loadOutputs: () => Promise<void>
  loadMoreOutputs: () => Promise<void>
  refreshOutputs: () => Promise<void>
  toggleFavorite: (name: string) => Promise<void>
  /** Fold late sizes and colours into listed outputs. Returns how many changed. */
  mergeOutputFacts: (facts: api.OutputFacts) => number
  selectedOutputMeta: OutputMetadata | null
  metadataLoading: boolean
  loadOutputMetadata: (name: string) => Promise<void>
  rejoinClipGroup: (groupId: string) => Promise<void>
  deleteSelectedOutput: () => Promise<void>
}

let _workspaceRequestEpoch = 0
let _workspaceListRequestEpoch = 0
let _pendingWorkspaceTransitionEpoch: number | null = null
let _outputRequestEpoch = 0
let _outputAbortController: AbortController | null = null
let _refreshAfterOutputRequest = false
let _metadataRequestEpoch = 0
let _metadataAbortController: AbortController | null = null
let _foCachedOutputs: OutputFile[] = []
let _foCachedFilter: MediaFilter = 'all'
let _foCachedResult: OutputFile[] = []

type WorkspaceOutputRequest = {
  workspace: string
  workspaceEpoch: number
  requestEpoch: number
  controller: AbortController
}

export function galleryWorkspaceName(state: { activeWorkspace: string; browsingUploads: boolean }): string {
  return state.browsingUploads ? '__uploads__' : state.activeWorkspace
}

export function galleryWorkspaceEpoch(): number {
  return _workspaceRequestEpoch
}

function _workspaceName(state: { activeWorkspace: string; browsingUploads: boolean }): string {
  return galleryWorkspaceName(state)
}

function _beginWorkspaceTransition(): number {
  _refreshAfterOutputRequest = false
  _workspaceRequestEpoch += 1
  _pendingWorkspaceTransitionEpoch = null
  _workspaceListRequestEpoch += 1
  _outputAbortController?.abort()
  _outputAbortController = null
  _metadataAbortController?.abort()
  _metadataAbortController = null
  _metadataRequestEpoch += 1
  return _workspaceRequestEpoch
}

function _beginOutputRequest(workspace: string): WorkspaceOutputRequest {
  _outputAbortController?.abort()
  const request: WorkspaceOutputRequest = {
    workspace,
    workspaceEpoch: _workspaceRequestEpoch,
    requestEpoch: ++_outputRequestEpoch,
    controller: new AbortController(),
  }
  _outputAbortController = request.controller
  return request
}

function _isCurrentOutputRequest(
  get: () => { activeWorkspace: string; browsingUploads: boolean },
  request: WorkspaceOutputRequest,
): boolean {
  return request.workspaceEpoch === _workspaceRequestEpoch
    && request.requestEpoch === _outputRequestEpoch
    && !request.controller.signal.aborted
    && _workspaceName(get()) === request.workspace
}

function _finishOutputRequest(request: WorkspaceOutputRequest, refresh: () => void): void {
  if (_outputAbortController !== request.controller) return
  _outputAbortController = null
  if (_refreshAfterOutputRequest) {
    _refreshAfterOutputRequest = false
    refresh()
  }
}

const FILTER_PREDICATES: Partial<Record<MediaFilter, (output: OutputFile) => boolean>> = {
  videos: output => output.type === 'video',
  images: output => output.type === 'image',
  audio: output => output.type === 'audio',
  model3d: output => output.type === 'model3d',
  scenes: output => output.type === 'scene',
  comics: output => output.type === 'comic',
  avatars: output => Boolean(output.edit_sub_mode) || output.mode === 'avatar',
  multiclip: output => output.type === 'video' && /multiclip|_mv\.mp4|_series_assembly|_movie\./i.test(output.name),
  videoclips: output => output.type === 'video' && output.result_kind === 'music_video',
  trailers: output => output.type === 'video' && output.result_kind === 'trailer',
  series_episodes: output => output.type === 'video' && (output.result_kind === 'series_episode' || output.result_kind === 'chapter'),
  favorites: output => Boolean(output.favorite),
}

function computeFilteredOutputs(outputs: OutputFile[], mediaFilter: MediaFilter): OutputFile[] {
  if (outputs === _foCachedOutputs && mediaFilter === _foCachedFilter) {
    return _foCachedResult
  }
  _foCachedOutputs = outputs
  _foCachedFilter = mediaFilter
  const predicate = FILTER_PREDICATES[mediaFilter]
  _foCachedResult = predicate ? outputs.filter(predicate) : outputs
  return _foCachedResult
}

function toOutputFile(output: api.ApiOutput): OutputFile {
  return {
    name: output.name,
    url: output.url,
    type: output.type,
    mode: (output.mode as OutputFile['mode']) || null,
    edit_sub_mode: (output.edit_sub_mode as OutputFile['edit_sub_mode']) || null,
    result_kind: (output.result_kind as OutputFile['result_kind']) || null,
    favorite: output.favorite || false,
    size: output.size,
    created_at: output.created_at,
    completed_at: output.completed_at,
    completion_time_source: output.completion_time_source,
    thumbnail_url: output.thumbnail_url || null,
    ...(output.width && output.height ? { width: output.width, height: output.height } : {}),
    ...(output.color && /^#[0-9a-f]{6}$/i.test(output.color) ? { color: output.color } : {}),
  }
}

function outputSnapshotEquals(current: OutputFile, latest: OutputFile): boolean {
  return latest.url === current.url
    && latest.type === current.type
    && latest.mode === current.mode
    && latest.edit_sub_mode === current.edit_sub_mode
    && latest.favorite === current.favorite
    && latest.size === current.size
    && latest.created_at === current.created_at
    && latest.completed_at === current.completed_at
    && latest.completion_time_source === current.completion_time_source
    && latest.thumbnail_url === current.thumbnail_url
    && latest.result_kind === current.result_kind
    && latest.width === current.width
    && latest.height === current.height
    && latest.color === current.color
}

function mergeRefreshedOutputs(current: OutputFile[], fresh: OutputFile[]): {
  merged: OutputFile[]
  newItems: OutputFile[]
  existingChanged: boolean
} {
  const currentNames = new Set(current.map(output => output.name))
  const newItems = fresh.filter(output => !currentNames.has(output.name))
  const currentByName = new Map(current.map(output => [output.name, output]))
  const merged = fresh.map(latest => {
    const output = currentByName.get(latest.name)
    return output && outputSnapshotEquals(output, latest) ? output : latest
  })
  return {
    merged,
    newItems,
    existingChanged: merged.length !== current.length || merged.some((output, index) => output !== current[index]),
  }
}

function clearedFeedState() {
  return {
    outputs: [] as OutputFile[],
    outputsTotal: 0,
    selectedOutput: 0,
    selectedOutputMeta: null,
    metadataLoading: false,
  }
}

export const createGallerySlice: SliceCreator<GallerySlice> = (set, get) => ({
  // Workspaces
  workspaces: [],
  activeWorkspace: 'default',
  browsingUploads: false,
  loadWorkspaces: async () => {
    const listRequestEpoch = ++_workspaceListRequestEpoch
    const pendingTransitionAtStart = _pendingWorkspaceTransitionEpoch
    try {
      const data = await api.fetchWorkspaces()
      if (
        listRequestEpoch !== _workspaceListRequestEpoch
        || pendingTransitionAtStart !== _pendingWorkspaceTransitionEpoch
        || pendingTransitionAtStart !== null
      ) return
      const previousWorkspace = get().activeWorkspace
      const browsingUploads = get().browsingUploads
      if (previousWorkspace !== data.active && !browsingUploads) {
        _beginWorkspaceTransition()
        set({
          workspaces: data.workspaces,
          activeWorkspace: data.active,
          ...clearedFeedState(),
        })
        void get().loadOutputs()
      } else {
        set({ workspaces: data.workspaces, activeWorkspace: data.active })
      }
    } catch (e) {
      console.error('Failed to load workspaces:', e)
    }
  },
  switchWorkspace: async (name) => {
    const transitionEpoch = _beginWorkspaceTransition()
    // Virtual "Uploads" view: browse the uploads folder WITHOUT touching
    // the server-side active workspace — generations keep saving to the
    // real workspace; uploads are read-only in the gallery.
    if (name === '__uploads__') {
      set({ browsingUploads: true, ...clearedFeedState() })
      void get().loadOutputs()
      return
    }
    _pendingWorkspaceTransitionEpoch = transitionEpoch
    try {
      await api.setActiveWorkspace(name)
      if (transitionEpoch !== _workspaceRequestEpoch) return
      _pendingWorkspaceTransitionEpoch = null
      set({ browsingUploads: false, activeWorkspace: name, ...clearedFeedState() })
      void get().loadOutputs()
      void get().loadWorkspaces()
    } catch (e) {
      if (transitionEpoch === _workspaceRequestEpoch) {
        _pendingWorkspaceTransitionEpoch = null
        set({ outputsLoading: false, metadataLoading: false })
      }
      console.error('Failed to switch workspace:', e)
    }
  },
  createWorkspace: async (name) => {
    const transitionEpoch = _beginWorkspaceTransition()
    _pendingWorkspaceTransitionEpoch = transitionEpoch
    try {
      await api.createWorkspace(name)
      await api.setActiveWorkspace(name)
      if (transitionEpoch !== _workspaceRequestEpoch) return
      _pendingWorkspaceTransitionEpoch = null
      set({ browsingUploads: false, activeWorkspace: name, ...clearedFeedState() })
      void get().loadOutputs()
      void get().loadWorkspaces()
    } catch (e) {
      if (transitionEpoch === _workspaceRequestEpoch) {
        _pendingWorkspaceTransitionEpoch = null
        set({ outputsLoading: false, metadataLoading: false })
      }
      console.error('Failed to create workspace:', e)
      throw e
    }
  },
  deleteWorkspace: async (name) => {
    // The server refuses 'default', refuses while anything generates, and
    // auto-switches to default when the deleted workspace was active —
    // its switched_to_default answer is authoritative (a client-side
    // activeWorkspace comparison could disagree after a desync and would
    // widen it by force-resetting state the server never changed).
    const workspaceEpoch = _workspaceRequestEpoch
    const result = await api.deleteWorkspace(name)
    if (workspaceEpoch !== _workspaceRequestEpoch) return
    if (result.switched_to_default) {
      _beginWorkspaceTransition()
      set({ browsingUploads: false, activeWorkspace: 'default', ...clearedFeedState() })
      void get().loadOutputs()
    }
    void get().loadWorkspaces()
  },

  outputs: [],
  outputsTotal: 0,
  selectedOutput: 0,
  setSelectedOutput: (i) => {
    set({ selectedOutput: i })
    const outputs = get().filteredOutputs()
    const output = outputs[i]
    if (output) {
      get().loadOutputMetadata(output.name)
    } else {
      set({ selectedOutputMeta: null })
    }
  },
  mediaFilter: 'all',
  galleryView: readStoredGalleryView(),
  setGalleryView: (view) => {
    set({ galleryView: view })
    try { localStorage.setItem(GALLERY_VIEW_KEY, view) } catch { /* private browsing */ }
  },
  galleryGridColumns: readStoredGridColumns(),
  setGalleryGridColumns: (columns) => {
    const [min, max] = GALLERY_GRID_COLUMN_RANGE
    const next = columns == null ? null : Math.min(max, Math.max(min, Math.round(columns)))
    set({ galleryGridColumns: next })
    try {
      if (next == null) localStorage.removeItem(GALLERY_GRID_COLUMNS_KEY)
      else localStorage.setItem(GALLERY_GRID_COLUMNS_KEY, String(next))
    } catch { /* private browsing */ }
  },
  galleryOrder: readStoredGalleryOrder(),
  setGalleryOrder: (order) => {
    if (get().galleryOrder === order) return
    set({ galleryOrder: order, selectedOutput: 0 })
    try { localStorage.setItem(GALLERY_ORDER_KEY, order) } catch { /* private browsing */ }
    void get().loadOutputs()
  },
  mobileHistoryOpen: false,
  setMobileHistoryOpen: (open) => set({ mobileHistoryOpen: open }),
  outputSearchQuery: '',
  galleryFeedAtTop: true,
  galleryRefreshPending: false,
  galleryToast: null,
  setMediaFilter: (f) => {
    const prevFilter = get().mediaFilter
    set({ mediaFilter: f, selectedOutput: 0, galleryFeedAtTop: true })
    if (GALLERY_LIST_FILTERS.has(f) || GALLERY_LIST_FILTERS.has(prevFilter)) {
      get().loadOutputs()
      return
    }
    const filtered = get().filteredOutputs()
    if (filtered.length > 0) {
      get().loadOutputMetadata(filtered[0].name)
    } else {
      set({ selectedOutputMeta: null })
    }
  },
  setGalleryFeedAtTop: (atTop) => {
    const wasTop = get().galleryFeedAtTop
    set({ galleryFeedAtTop: atTop })
    if (atTop && !wasTop && get().galleryRefreshPending) {
      set({ galleryRefreshPending: false })
      // Keep the already-paged window. loadOutputs() always asks for the
      // first 100 rows and would drop everything the reader had scrolled in.
      void get().refreshOutputs()
    }
  },
  clearGalleryToast: () => set({ galleryToast: null }),
  maybeRefreshGallery: async (opts) => {
    const filter = get().mediaFilter
    if (opts?.message) {
      set({ galleryToast: { id: Date.now(), message: opts.message } })
    }
    if (!GALLERY_LIST_FILTERS.has(filter)) {
      set({ galleryRefreshPending: true })
      return
    }
    if (!get().galleryFeedAtTop && !opts?.force) {
      set({ galleryRefreshPending: true })
      return
    }
    set({ galleryRefreshPending: false })
    await get().refreshOutputs()
  },
  setOutputSearchQuery: (q) => {
    const previous = get().outputSearchQuery.trim()
    set({ outputSearchQuery: q, selectedOutput: 0 })
    // Any change reloads, including clearing a search on a filtered tab,
    // which used to leave the search results on screen.
    if (q.trim() !== previous) void get().loadOutputs()
  },
  filteredOutputs: () => {
    const { outputs, mediaFilter } = get()
    return computeFilteredOutputs(outputs, mediaFilter)
  },

  outputsLoading: false,
  loadOutputs: async () => {
    const PAGE_SIZE = 100
    const { mediaFilter, outputSearchQuery } = get()
    const workspace = _workspaceName(get())
    const request = _beginOutputRequest(workspace)
    const query = galleryListQuery(mediaFilter, outputSearchQuery)
    set({ outputsLoading: true, galleryRefreshPending: false })
    try {
      const { outputs: apiOutputs, total } = query.useServerList
        ? await api.fetchOutputs(query.resultKind || query.favoritesOnly || query.multiclipOnly || query.editsOnly || query.search ? 0 : PAGE_SIZE, 0, {
            order: get().galleryOrder,
            favoritesOnly: query.favoritesOnly,
            multiclipOnly: query.multiclipOnly,
            editsOnly: query.editsOnly,
            resultKind: query.resultKind,
            mediaType: query.mediaType,
            search: query.search,
            workspace,
            signal: request.controller.signal,
          })
        : await api.fetchOutputs(PAGE_SIZE, 0, { workspace, order: get().galleryOrder, signal: request.controller.signal })
      if (!_isCurrentOutputRequest(get, request)) return
      const outputs: OutputFile[] = apiOutputs.map(toOutputFile)
      const previousName = get().filteredOutputs()[get().selectedOutput]?.name
      const found = previousName ? outputs.findIndex(item => item.name === previousName) : -1
      const nextIndex = found >= 0 ? found : 0
      set({ outputs, outputsTotal: total, selectedOutput: nextIndex, outputsLoading: false })
      if (outputs.length > 0) {
        void get().loadOutputMetadata(outputs[nextIndex].name)
      }
    } catch (e) {
      if (!_isCurrentOutputRequest(get, request)) return
      console.error('Failed to load outputs:', e)
      set({ outputsLoading: false })
    } finally {
      _finishOutputRequest(request, () => { void get().maybeRefreshGallery() })
    }
  },

  // Load next page of outputs (infinite scroll)
  loadMoreOutputs: async () => {
    if (_outputAbortController) return
    const PAGE_SIZE = 100
    const current = get().outputs
    const total = get().outputsTotal
    if (current.length >= total) return // All loaded
    const workspace = _workspaceName(get())
    const request = _beginOutputRequest(workspace)
    try {
      const query = galleryListQuery(get().mediaFilter, get().outputSearchQuery)
      const { outputs: apiOutputs, total: newTotal } = await api.fetchOutputs(PAGE_SIZE, current.length, {
        workspace,
        order: get().galleryOrder,
        mediaType: query.mediaType,
        resultKind: query.resultKind,
        favoritesOnly: query.favoritesOnly,
        multiclipOnly: query.multiclipOnly,
        editsOnly: query.editsOnly,
        search: query.search,
        signal: request.controller.signal,
      })
      if (!_isCurrentOutputRequest(get, request)) return
      const more: OutputFile[] = apiOutputs.map(toOutputFile)
      // Deduplicate (in case items shifted during generation)
      const existingNames = new Set(current.map(o => o.name))
      const unique = more.filter(o => !existingNames.has(o.name))
      if (unique.length > 0) {
        set({ outputs: [...current, ...unique], outputsTotal: newTotal })
      }
    } catch {
      // Silent fail
    } finally {
      _finishOutputRequest(request, () => { void get().maybeRefreshGallery() })
    }
  },

  // Incremental refresh: only fetch the newest items to detect new outputs during generation
  refreshOutputs: async () => {
    // Heartbeats must not abort initial loading, paging or another refresh.
    // Coalesce concurrent heartbeats into one trailing refresh, including a
    // completion that arrives during the initial request.
    if (_outputAbortController) { _refreshAfterOutputRequest = true; return }
    const workspace = _workspaceName(get())
    const request = _beginOutputRequest(workspace)
    const query = galleryListQuery(get().mediaFilter, get().outputSearchQuery)
    try {
      // Reconcile the loaded window in the server's chosen order, including
      // deletions and replacements made by another browser.
      const { outputs: apiOutputs, total } = await api.fetchOutputs(Math.max(100, get().outputs.length), 0, {
        order: get().galleryOrder,
        workspace,
        mediaType: query.mediaType,
        resultKind: query.resultKind,
        favoritesOnly: query.favoritesOnly,
        multiclipOnly: query.multiclipOnly,
        editsOnly: query.editsOnly,
        search: query.search,
        signal: request.controller.signal,
      })
      if (!_isCurrentOutputRequest(get, request)) return
      const current = get().outputs
      const { merged, newItems, existingChanged } = mergeRefreshedOutputs(current, apiOutputs.map(toOutputFile))
      if (newItems.length > 0 || existingChanged || total !== get().outputsTotal) {
        const watchingGallery = GALLERY_LIST_FILTERS.has(get().mediaFilter)
        if (!watchingGallery || !get().galleryFeedAtTop) {
          set({ galleryRefreshPending: true })
          if (newItems.length > 0 && !get().galleryToast) {
            const noun = newItems.length === 1 ? 'item' : 'items'
            set({ galleryToast: { id: Date.now(), message: `${newItems.length} new ${noun} ready` } })
          }
          return
        }
        const selectedName = get().filteredOutputs()[get().selectedOutput]?.name
        const selected = computeFilteredOutputs(merged, get().mediaFilter).findIndex(file => file.name === selectedName)
        set({ outputs: merged, outputsTotal: total, selectedOutput: Math.max(0, selected) })
      }
    } catch {
      // Silent fail for background refresh
    } finally {
      if (_isCurrentOutputRequest(get, request)) set({ outputsLoading: false })
      _finishOutputRequest(request, () => { void get().maybeRefreshGallery() })
    }
  },

  mergeOutputFacts: (facts) => {
    let changed = 0
    const outputs = get().outputs.map(file => {
      const fact = facts[file.name]
      if (!fact) return file
      const width = fact.width && fact.height ? fact.width : file.width
      const height = fact.width && fact.height ? fact.height : file.height
      const color = fact.color && /^#[0-9a-f]{6}$/i.test(fact.color) ? fact.color : file.color
      if (width === file.width && height === file.height && color === file.color) return file
      changed += 1
      return { ...file, width, height, color }
    })
    if (changed) set({ outputs })
    return changed
  },
  toggleFavorite: async (name) => {
    const workspace = _workspaceName(get())
    const workspaceEpoch = _workspaceRequestEpoch
    try {
      const result = await api.toggleFavorite(name)
      if (workspaceEpoch !== _workspaceRequestEpoch || _workspaceName(get()) !== workspace) return
      set(s => ({
        outputs: s.outputs.map(o => o.name === name ? { ...o, favorite: result.favorite } : o),
      }))
    } catch (e) {
      console.error('Failed to toggle favorite:', e)
    }
  },

  // Output metadata
  selectedOutputMeta: null,
  metadataLoading: false,

  loadOutputMetadata: async (name) => {
    const workspace = _workspaceName(get())
    const metadataRequestEpoch = ++_metadataRequestEpoch
    _metadataAbortController?.abort()
    const controller = new AbortController()
    _metadataAbortController = controller
    set({ metadataLoading: true, selectedOutputMeta: null })
    try {
      const meta = await api.fetchOutputMetadata(name, workspace, controller.signal)
      if (metadataRequestEpoch !== _metadataRequestEpoch || _workspaceName(get()) !== workspace) return
      set({ selectedOutputMeta: meta, metadataLoading: false })
    } catch (e) {
      if (metadataRequestEpoch !== _metadataRequestEpoch || _workspaceName(get()) !== workspace) return
      // Diagnostic: surface metadata-fetch failures (the usual cause of a
      // "Load Settings does nothing" report on slow/VPN links) instead of
      // swallowing them silently.
      console.error('[LoadSettings] fetchOutputMetadata FAILED for', name, '-', e)
      set({ selectedOutputMeta: null, metadataLoading: false })
    } finally {
      if (_metadataAbortController === controller) _metadataAbortController = null
    }
  },

  rejoinClipGroup: async (groupId) => {
    const workspace = _workspaceName(get())
    const workspaceEpoch = _workspaceRequestEpoch
    try {
      const result = await api.rejoinClips(groupId)
      if (workspaceEpoch !== _workspaceRequestEpoch || _workspaceName(get()) !== workspace) return
      // Refresh through the epoch-aware, workspace-explicit gallery loader.
      await get().loadOutputs()
      if (workspaceEpoch !== _workspaceRequestEpoch || _workspaceName(get()) !== workspace) return
      // Select the new file
      const allOutputs = get().outputs
      const newIdx = allOutputs.findIndex(o => o.name === result.filename)
      if (newIdx >= 0) {
        set({ selectedOutput: newIdx })
        get().loadOutputMetadata(result.filename)
      }
    } catch (e) {
      console.error('Failed to rejoin clips:', e)
    }
  },

  deleteSelectedOutput: async () => {
    const outputs = get().filteredOutputs()
    const idx = get().selectedOutput
    const output = outputs[idx]
    if (!output) return
    const workspace = _workspaceName(get())
    const workspaceEpoch = _workspaceRequestEpoch

    try {
      await api.deleteOutput(output.name)
      if (workspaceEpoch !== _workspaceRequestEpoch || _workspaceName(get()) !== workspace) return
      // Remove from local state
      const allOutputs = get().outputs.filter(o => o.name !== output.name)
      const newIdx = Math.min(idx, Math.max(0, allOutputs.length - 1))
      set({ outputs: allOutputs, selectedOutput: newIdx })
      // Load metadata for new selection
      const newFiltered = get().filteredOutputs()
      if (newFiltered[newIdx]) {
        get().loadOutputMetadata(newFiltered[newIdx].name)
      } else {
        set({ selectedOutputMeta: null })
      }
    } catch (e) {
      console.error('Failed to delete output:', e)
    }
  },

})
