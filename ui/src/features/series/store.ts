import { create } from 'zustand'
import * as api from '../../api/client'
import { emptySeriesLibrary, normalizeSeriesLibrary, normalizeSeriesProject } from './model'
import type { SeriesEpisode, SeriesJobStatus, SeriesLibrary, SeriesProject } from './types'

const activeKey = (workspace: string): string => `maestro-series-lab-active:${workspace}`

interface SeriesState {
  workspace: string
  library: SeriesLibrary
  activeSeriesId: string
  activeEpisodeId: string
  serverRevision: number
  hydrated: boolean
  loading: boolean
  dirty: boolean
  saving: boolean
  error: string | null
  planRecovery: SeriesJobStatus[]
  renderRecovery: SeriesJobStatus[]
  loadWorkspace: (workspace: string) => Promise<void>
  reload: () => Promise<void>
  openSeries: (seriesId: string) => void
  openEpisode: (episodeId: string) => void
  patchSeries: (patch: Partial<SeriesProject>) => void
  updateSeries: (updater: (series: SeriesProject) => SeriesProject) => void
  updateEpisode: (episodeId: string, updater: (episode: SeriesEpisode) => SeriesEpisode) => void
  adoptRemoteSeries: (series: SeriesProject) => void
  saveNow: () => Promise<SeriesProject | null>
  newSeries: () => Promise<void>
  duplicateSeries: (seriesId?: string) => Promise<void>
  deleteSeries: (seriesId?: string) => Promise<void>
  importStory: (storyId: string) => Promise<void>
  createEpisode: () => Promise<void>
  deleteEpisode: (episodeId?: string) => Promise<void>
  refreshRecovery: () => Promise<void>
}

const initialWorkspace = 'default'

function selectedSeries(state: Pick<SeriesState, 'library' | 'activeSeriesId'>): SeriesProject | null {
  return state.library.seriesById[state.activeSeriesId] || null
}

function firstEpisodeId(series: SeriesProject | null): string {
  if (!series) return ''
  for (const season of series.seasons) {
    const episodeId = season.episodeOrder.find(id => series.episodesById[id])
    if (episodeId) return episodeId
  }
  return Object.keys(series.episodesById)[0] || ''
}

function rememberSelection(workspace: string, seriesId: string, episodeId: string): void {
  try {
    window.localStorage.setItem(activeKey(workspace), JSON.stringify({ seriesId, episodeId }))
  } catch {
    // Selection persistence is optional; the backend library remains authoritative.
  }
}

function restoredSelection(workspace: string): { seriesId?: string; episodeId?: string } {
  try {
    const value = JSON.parse(window.localStorage.getItem(activeKey(workspace)) || '{}')
    return value && typeof value === 'object' ? value : {}
  } catch {
    return {}
  }
}

let saveTimer: number | undefined
let saveInFlight: Promise<SeriesProject | null> | null = null

export const useSeriesStore = create<SeriesState>((set, get) => ({
  workspace: initialWorkspace,
  library: emptySeriesLibrary(initialWorkspace),
  activeSeriesId: '',
  activeEpisodeId: '',
  serverRevision: 0,
  hydrated: false,
  loading: false,
  dirty: false,
  saving: false,
  error: null,
  planRecovery: [],
  renderRecovery: [],

  loadWorkspace: async rawWorkspace => {
    const workspace = rawWorkspace.trim() || 'default'
    if (workspace === get().workspace && (get().loading || get().hydrated)) return
    window.clearTimeout(saveTimer)
    if (get().dirty) {
      try { await get().saveNow() } catch { /* the error remains visible */ }
    }
    set({ workspace, loading: true, hydrated: false, error: null })
    try {
      const library = normalizeSeriesLibrary(await api.fetchSeriesLibrary(workspace), workspace)
      const restored = restoredSelection(workspace)
      const activeSeriesId = restored.seriesId && library.seriesById[restored.seriesId]
        ? restored.seriesId : library.seriesOrder[0] || ''
      const series = library.seriesById[activeSeriesId] || null
      const activeEpisodeId = restored.episodeId && series?.episodesById[restored.episodeId]
        ? restored.episodeId : firstEpisodeId(series)
      set({
        library, activeSeriesId, activeEpisodeId,
        serverRevision: series?.revision || 0,
        loading: false, hydrated: true, dirty: false, saving: false, error: null,
      })
      rememberSelection(workspace, activeSeriesId, activeEpisodeId)
      await get().refreshRecovery()
    } catch (error) {
      set({
        loading: false, hydrated: false,
        error: error instanceof Error ? error.message : 'Series Lab storage is unavailable',
      })
    }
  },

  reload: async () => {
    const workspace = get().workspace
    set({ hydrated: false })
    await get().loadWorkspace(workspace)
  },

  openSeries: seriesId => {
    const series = get().library.seriesById[seriesId]
    if (!series) return
    const episodeId = firstEpisodeId(series)
    set({ activeSeriesId: seriesId, activeEpisodeId: episodeId, serverRevision: series.revision, error: null })
    rememberSelection(get().workspace, seriesId, episodeId)
  },

  openEpisode: episodeId => {
    const series = selectedSeries(get())
    if (!series?.episodesById[episodeId]) return
    set({ activeEpisodeId: episodeId })
    rememberSelection(get().workspace, series.id, episodeId)
  },

  patchSeries: patch => get().updateSeries(series => ({ ...series, ...patch })),

  updateSeries: updater => {
    const state = get()
    const current = selectedSeries(state)
    if (!current) return
    const candidate = normalizeSeriesProject({
      ...updater(structuredClone(current)),
      id: current.id, revision: current.revision, createdAt: current.createdAt,
      updatedAt: new Date().toISOString(),
    })
    if (!candidate) return
    set({
      library: {
        ...state.library,
        seriesById: { ...state.library.seriesById, [candidate.id]: candidate },
      },
      dirty: true, error: null,
    })
    window.clearTimeout(saveTimer)
    saveTimer = window.setTimeout(() => { void get().saveNow() }, 750)
  },

  updateEpisode: (episodeId, updater) => get().updateSeries(series => {
    const episode = series.episodesById[episodeId]
    if (!episode) return series
    return {
      ...series,
      episodesById: {
        ...series.episodesById,
        [episodeId]: { ...updater(structuredClone(episode)), id: episode.id, updatedAt: new Date().toISOString() },
      },
    }
  }),

  adoptRemoteSeries: value => {
    const project = normalizeSeriesProject(value)
    if (!project) return
    const state = get()
    set({
      library: {
        ...state.library,
        seriesById: { ...state.library.seriesById, [project.id]: project },
      },
      activeSeriesId: project.id,
      activeEpisodeId: state.activeEpisodeId && project.episodesById[state.activeEpisodeId]
        ? state.activeEpisodeId : firstEpisodeId(project),
      serverRevision: project.revision,
      dirty: false,
      error: null,
    })
  },

  saveNow: async () => {
    window.clearTimeout(saveTimer)
    const state = get()
    const project = selectedSeries(state)
    if (state.saving && saveInFlight) {
      const saved = await saveInFlight
      return get().dirty ? get().saveNow() : saved
    }
    if (!project || !state.dirty) return project
    const snapshotUpdatedAt = project.updatedAt
    const baseRevision = state.serverRevision || project.revision
    set({ saving: true })
    saveInFlight = (async () => {
      try {
        const saved = normalizeSeriesProject(await api.saveSeriesProject(
          state.workspace, project, baseRevision,
        ))
        if (!saved) throw new Error('Series Lab returned an invalid project')
        const latest = get()
        const current = selectedSeries(latest)
        const untouchedDuringSave = current?.updatedAt === snapshotUpdatedAt
        const visible = untouchedDuringSave ? saved : current ? { ...current, revision: saved.revision } : saved
        set({
          library: {
            ...latest.library,
            seriesById: { ...latest.library.seriesById, [saved.id]: visible },
          },
          serverRevision: saved.revision,
          dirty: !untouchedDuringSave,
          saving: false,
          error: null,
        })
        if (!untouchedDuringSave) {
          window.clearTimeout(saveTimer)
          saveTimer = window.setTimeout(() => { void get().saveNow() }, 100)
        }
        return visible
      } catch (error) {
        set({
          saving: false, dirty: true,
          error: error instanceof Error ? error.message : 'Series Lab autosave failed',
        })
        throw error
      } finally {
        saveInFlight = null
      }
    })()
    const saved = await saveInFlight
    return get().dirty ? get().saveNow() : saved
  },

  newSeries: async () => {
    await get().saveNow()
    const project = await api.createSeriesProject(get().workspace)
    const state = get()
    set({
      library: {
        ...state.library,
        seriesOrder: [...state.library.seriesOrder, project.id],
        seriesById: { ...state.library.seriesById, [project.id]: project },
      },
      activeSeriesId: project.id, activeEpisodeId: '', serverRevision: project.revision,
      dirty: false, error: null,
    })
    rememberSelection(state.workspace, project.id, '')
  },

  duplicateSeries: async seriesId => {
    await get().saveNow()
    const sourceId = seriesId || get().activeSeriesId
    if (!sourceId) return
    const project = await api.duplicateSeriesProject(get().workspace, sourceId)
    const state = get()
    const sourceIndex = state.library.seriesOrder.indexOf(sourceId)
    const order = [...state.library.seriesOrder]
    order.splice(sourceIndex + 1, 0, project.id)
    set({
      library: { ...state.library, seriesOrder: order, seriesById: { ...state.library.seriesById, [project.id]: project } },
      activeSeriesId: project.id, activeEpisodeId: firstEpisodeId(project),
      serverRevision: project.revision, dirty: false, error: null,
    })
  },

  deleteSeries: async seriesId => {
    const id = seriesId || get().activeSeriesId
    if (!id) return
    await api.deleteSeriesProject(get().workspace, id)
    const state = get()
    const seriesById = { ...state.library.seriesById }
    delete seriesById[id]
    const seriesOrder = state.library.seriesOrder.filter(item => item !== id)
    const activeSeriesId = state.activeSeriesId === id ? seriesOrder[0] || '' : state.activeSeriesId
    const series = seriesById[activeSeriesId] || null
    set({
      library: { ...state.library, seriesOrder, seriesById }, activeSeriesId,
      activeEpisodeId: firstEpisodeId(series), serverRevision: series?.revision || 0,
      dirty: false, error: null,
    })
  },

  importStory: async storyId => {
    await get().saveNow()
    const project = await api.importStoryAsSeries(get().workspace, storyId)
    const state = get()
    set({
      library: {
        ...state.library,
        seriesOrder: [...state.library.seriesOrder, project.id],
        seriesById: { ...state.library.seriesById, [project.id]: project },
      },
      activeSeriesId: project.id, activeEpisodeId: firstEpisodeId(project),
      serverRevision: project.revision, dirty: false, error: null,
    })
  },

  createEpisode: async () => {
    await get().saveNow()
    const state = get()
    const series = selectedSeries(state)
    if (!series) return
    const episode = await api.createSeriesEpisode(state.workspace, series.id, series.seasons[0]?.id)
    await get().reload()
    get().openEpisode(episode.id)
  },

  deleteEpisode: async episodeId => {
    await get().saveNow()
    const state = get()
    const series = selectedSeries(state)
    const id = episodeId || state.activeEpisodeId
    if (!series || !id) return
    await api.deleteSeriesEpisode(state.workspace, series.id, id)
    await get().reload()
  },

  refreshRecovery: async () => {
    const workspace = get().workspace
    try {
      const [plans, renders] = await Promise.all([
        api.fetchSeriesPlanRecovery(workspace), api.fetchSeriesRenderRecovery(workspace),
      ])
      if (get().workspace === workspace) set({ planRecovery: plans.jobs, renderRecovery: renders.jobs })
    } catch {
      // Recovery cards are supplementary; normal library editing remains available.
    }
  },
}))
