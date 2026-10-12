import { create } from 'zustand'
import * as api from '../../api/client'
import { emptySeriesLibrary, normalizeSeriesLibrary, normalizeSeriesProject } from './model'
import type { SeriesEpisode, SeriesJobStatus, SeriesLibrary, SeriesProject, SeriesReviewChange, SeriesReviewReply } from './types'
import { editSeriesShot, type SeriesShotEditBody, type SeriesShotEditReply } from '../../api/seriesShotInspector'
import { mergeSeriesReferenceImport, type SeriesReferenceImport } from './referenceImages'

export interface SeriesWriteScope { workspace: string; seriesId: string }
export interface SeriesRemoteScope extends SeriesWriteScope { snapshot: SeriesProject }

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
  openSeries: (seriesId: string) => Promise<void>
  openEpisode: (episodeId: string) => void
  patchSeries: (patch: Partial<SeriesProject>) => void
  updateSeries: (updater: (series: SeriesProject) => SeriesProject) => void
  updateEpisode: (episodeId: string, updater: (episode: SeriesEpisode) => SeriesEpisode) => void
  adoptRemoteSeries: (series: SeriesProject, scope?: SeriesRemoteScope) => void
  acceptAssetImport: (workspace: string, result: SeriesReferenceImport) => void
  saveNow: () => Promise<SeriesProject | null>
  /** Send one review change (mode, approvals, notes) after pending edits; merges the server's review without losing edits. */
  saveReview: (episodeId: string, change: SeriesReviewChange, scope?: SeriesWriteScope) => Promise<SeriesReviewReply>
  /** Edit one shot on the server after pending edits. */
  editShot: (episodeId: string, body: SeriesShotEditBody, scope?: SeriesWriteScope) => Promise<SeriesShotEditReply>
  /** An episode the server just wrote and the revision it left. */
  acceptEpisode: (seriesId: string, episode: SeriesEpisode, revision: number, scope: SeriesRemoteScope) => void
  newSeries: () => Promise<void>
  newSeriesFromTemplate: (templateId: string, language: 'es' | 'en') => Promise<void>
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
let reviewTail: Promise<void> = Promise.resolve()

/** A full remote snapshot may only replace the unchanged project it was requested for. */
function acceptsRemote(state: SeriesState, scope: SeriesRemoteScope, revision: number): boolean {
  return state.workspace === scope.workspace && state.activeSeriesId === scope.seriesId && !state.dirty
    && state.library.seriesById[scope.seriesId] === scope.snapshot && revision >= Math.max(state.serverRevision, scope.snapshot.revision)
}

/** Reviews and inspector edits reserve the same queue before waiting for autosave. */
function queueEpisodeWrite<T extends { revision: number }>(
  set: (state: Partial<SeriesState>) => void, get: () => SeriesState, episodeId: string, expected: SeriesWriteScope | undefined,
  write: (scope: SeriesWriteScope) => Promise<T>, merge: (project: SeriesProject, reply: T, snapshot: SeriesProject) => SeriesProject,
): Promise<T> {
  const initial = get(), scope = expected ?? { workspace: initial.workspace, seriesId: initial.activeSeriesId }
  const revision = initial.library.seriesById[scope.seriesId]?.revision || 0
  const currentScope = () => get().workspace === scope.workspace && get().activeSeriesId === scope.seriesId
  const result = reviewTail.then(async () => {
    if (!currentScope()) throw new Error('The series workspace or project changed')
    await get().saveNow()
    if (!currentScope()) throw new Error('The series workspace or project changed')
    const snapshot = selectedSeries(get())
    if (!snapshot?.episodesById[episodeId]) throw new Error('Series episode not found')
    const request = write(scope).then(reply => {
      const latest = get(), current = latest.library.seriesById[scope.seriesId]
      if (latest.workspace !== scope.workspace || !current || reply.revision < Math.max(revision, snapshot.revision, current.revision)) return reply
      set({
        library: { ...latest.library, seriesById: { ...latest.library.seriesById, [scope.seriesId]: merge(current, reply, snapshot) } },
        serverRevision: latest.activeSeriesId === scope.seriesId ? reply.revision : latest.serverRevision,
      })
      return reply
    })
    set({ saving: true })
    const held = request.then(() => selectedSeries(get()), () => selectedSeries(get())).finally(() => {
      if (saveInFlight === held) { saveInFlight = null; set({ saving: false }) }
    })
    saveInFlight = held
    try { return await request }
    finally {
      await held
      if (currentScope() && get().dirty) void get().saveNow().catch(() => { /* Store exposes the save error. */ })
    }
  })
  reviewTail = result.then(() => {}, () => {})
  return result
}

/** The series with the server's review of one episode and its new revision; every other local field is kept. */
function withReview(series: SeriesProject, reply: SeriesReviewReply): SeriesProject {
  const episode = series.episodesById[reply.episodeId]
  if (!episode) return { ...series, revision: reply.revision }
  return {
    ...series, revision: reply.revision,
    episodesById: { ...series.episodesById, [reply.episodeId]: { ...episode, review: reply.review, updatedAt: reply.episodeUpdatedAt || episode.updatedAt } },
  }
}

/** The series with one shot as the server stored it after an edit, the episode's new review and versions; the rest kept. */
function withShotEdit(series: SeriesProject, reply: SeriesShotEditReply, snapshot: SeriesProject): SeriesProject {
  const stored = reply.stored
  const episode = stored && series.episodesById[stored.episodeId]
  if (!stored || !episode) return { ...series, revision: reply.revision }
  const before = snapshot.episodesById[stored.episodeId]?.shots.find(shot => shot.id === stored.shot.id)
  const current = episode.shots.find(shot => shot.id === stored.shot.id)
  if (JSON.stringify(before) !== JSON.stringify(current)) throw new Error('The shot changed while saving; its local edits have been kept')
  const next: SeriesEpisode = {
    ...episode, shots: episode.shots.map(shot => shot.id === stored.shot.id ? stored.shot : shot),
    updatedAt: stored.episodeUpdatedAt || episode.updatedAt,
  }
  if (stored.review) next.review = stored.review; else delete next.review
  if (stored.languageVersions) next.languageVersions = stored.languageVersions
  return { ...series, revision: reply.revision, episodesById: { ...series.episodesById, [stored.episodeId]: next } }
}

/** Add a series the server just created to the library and open it. */
function adoptNewSeries(set: (partial: Partial<SeriesState>) => void, get: () => SeriesState, project: SeriesProject) {
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
}

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
      try {
        await get().saveNow()
      } catch {
        // Keep the current workspace selected when its edits cannot be saved.
        // Switching here would hide the unsaved project and make recovery
        // unnecessarily difficult.
        return
      }
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

  openSeries: async seriesId => {
    if (seriesId === get().activeSeriesId) return
    window.clearTimeout(saveTimer)
    if (get().dirty) {
      try {
        await get().saveNow()
      } catch {
        // Stay on the edited project. Its visible save error explains why
        // navigation did not proceed and prevents silently abandoning changes.
        return
      }
    }
    const state = get()
    const series = state.library.seriesById[seriesId]
    if (!series) return
    const episodeId = firstEpisodeId(series)
    set({ activeSeriesId: seriesId, activeEpisodeId: episodeId, serverRevision: series.revision, error: null })
    rememberSelection(state.workspace, seriesId, episodeId)
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

  adoptRemoteSeries: (value, scope) => {
    if (scope && (value.id !== scope.seriesId || !acceptsRemote(get(), scope, value.revision))) return
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

  acceptAssetImport: (workspace, result) => {
    const state = get()
    if (state.workspace !== workspace) return
    const current = state.library.seriesById[result.series.id]
    if (!current) return
    const active = state.activeSeriesId === current.id
    const project = (active && state.dirty) || current.revision > result.series.revision ? mergeSeriesReferenceImport(current, result) : result.series
    set({ library: { ...state.library, seriesById: { ...state.library.seriesById, [current.id]: project } },
      ...(active ? { serverRevision: project.revision } : {}),
    })
    if (active && state.dirty) void get().saveNow().catch(() => { /* Store exposes the save error. */ })
  },

  saveNow: async () => {
    window.clearTimeout(saveTimer)
    const state = get()
    const project = selectedSeries(state)
    const projectId = project?.id || ''
    if (state.saving && saveInFlight) {
      const saved = await saveInFlight
      return get().activeSeriesId === projectId && get().dirty ? get().saveNow() : saved
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
        const current = latest.library.seriesById[projectId] || null
        const untouchedDuringSave = current?.updatedAt === snapshotUpdatedAt
        const visible = untouchedDuringSave ? saved : current ? { ...current, revision: saved.revision } : saved
        const stillActive = latest.activeSeriesId === projectId
        set({
          library: {
            ...latest.library,
            seriesById: { ...latest.library.seriesById, [saved.id]: visible },
          },
          serverRevision: stillActive ? saved.revision : latest.serverRevision,
          dirty: stillActive ? !untouchedDuringSave : latest.dirty,
          saving: false,
          error: null,
        })
        if (stillActive && !untouchedDuringSave) {
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
    return get().activeSeriesId === projectId && get().dirty ? get().saveNow() : saved
  },

  saveReview: (episodeId, change, scope) => queueEpisodeWrite(set, get, episodeId, scope,
    target => api.saveSeriesEpisodeReview(target.workspace, target.seriesId, episodeId, change), withReview),

  editShot: (episodeId, body, scope) => queueEpisodeWrite(set, get, episodeId, scope,
    target => editSeriesShot(target.workspace, target.seriesId, episodeId, body), withShotEdit),

  acceptEpisode: (seriesId, episode, revision, scope) => {
    const latest = get()
    const current = latest.library.seriesById[seriesId]
    if (!current || seriesId !== scope.seriesId || !acceptsRemote(latest, scope, revision)) return
    set({
      library: { ...latest.library, seriesById: { ...latest.library.seriesById, [seriesId]: {
        ...current, revision, episodesById: { ...current.episodesById, [episode.id]: episode } } } },
      serverRevision: latest.activeSeriesId === seriesId ? revision : latest.serverRevision,
    })
  },

  newSeries: async () => {
    await get().saveNow()
    adoptNewSeries(set, get, await api.createSeriesProject(get().workspace))
  },

  newSeriesFromTemplate: async (templateId, language) => {
    await get().saveNow()
    adoptNewSeries(set, get, await api.createSeriesFromTemplate(get().workspace, templateId, language))
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
