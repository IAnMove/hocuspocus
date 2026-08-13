import { create } from 'zustand'
import * as api from '../../api/client'
import { changedSections, createStoryProject, normalizeStoryProject } from './model'
import type { StoryProject, StoryProjectType } from './types'

const LEGACY_AUTOSAVE_KEY = 'maestro-story-lab-v1'
const LIBRARY_PREFIX = 'maestro-story-library-v2:'

interface StoryLibraryData {
  version: 2
  activeId: string
  projects: Record<string, StoryProject>
}

const safeWorkspace = (workspace: string): string =>
  workspace.trim().replace(/[^a-zA-Z0-9._-]+/g, '-') || 'default'
const libraryKey = (workspace: string): string => `${LIBRARY_PREFIX}${safeWorkspace(workspace)}`

function normalizeLibrary(value: unknown): StoryLibraryData | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Partial<StoryLibraryData>
  if (!raw.projects || typeof raw.projects !== 'object') return null
  const projects = Object.fromEntries(
    Object.values(raw.projects).map(item => {
      const project = normalizeStoryProject(item)
      return [project.id, project]
    }),
  )
  const firstId = Object.keys(projects)[0]
  if (!firstId) return null
  const activeId = typeof raw.activeId === 'string' && projects[raw.activeId]
    ? raw.activeId : firstId
  return { version: 2, activeId, projects }
}

function restoreLocalLibrary(workspace: string): StoryLibraryData {
  const fallback = createStoryProject()
  if (typeof window === 'undefined') {
    return { version: 2, activeId: fallback.id, projects: { [fallback.id]: fallback } }
  }
  try {
    const raw = JSON.parse(window.localStorage.getItem(libraryKey(workspace)) || 'null')
    const restored = normalizeLibrary(raw)
    if (restored) return restored
    const legacy = workspace === 'default'
      ? JSON.parse(window.localStorage.getItem(LEGACY_AUTOSAVE_KEY) || 'null')
      : null
    if (legacy) {
      const project = normalizeStoryProject(legacy)
      return { version: 2, activeId: project.id, projects: { [project.id]: project } }
    }
  } catch {
    // Fall through to a clean, valid library.
  }
  return { version: 2, activeId: fallback.id, projects: { [fallback.id]: fallback } }
}

function buildLibrary(
  project: StoryProject,
  projects: Record<string, StoryProject>,
): StoryLibraryData {
  return {
    version: 2,
    activeId: project.id,
    projects: { ...projects, [project.id]: project },
  }
}

function persistLocalLibrary(
  workspace: string,
  project: StoryProject,
  projects: Record<string, StoryProject>,
): void {
  if (typeof window === 'undefined') return
  window.localStorage.setItem(
    libraryKey(workspace),
    JSON.stringify(buildLibrary(project, projects)),
  )
}

function touched(before: StoryProject, candidate: StoryProject): StoryProject {
  const after = normalizeStoryProject(candidate)
  const sections = changedSections(before, after)
  const sectionVersions = { ...before.sectionVersions }
  sections.forEach(section => { sectionVersions[section] += 1 })
  return {
    ...after,
    revision: Math.max(1, before.revision + 1),
    sectionVersions,
    updatedAt: new Date().toISOString(),
  }
}

interface StoryState {
  workspace: string
  project: StoryProject
  projects: Record<string, StoryProject>
  dirty: boolean
  hydrated: boolean
  loading: boolean
  saveError: string | null
  loadWorkspace: (workspace: string) => Promise<void>
  setProject: (project: StoryProject) => void
  patchProject: (patch: Partial<StoryProject>) => void
  updateProject: (updater: (project: StoryProject) => StoryProject) => void
  newProject: (projectType?: StoryProjectType) => void
  duplicateProject: (id?: string) => void
  openProject: (id: string) => void
  deleteProject: (id: string) => void
}

const initialWorkspace = 'default'
const restored = restoreLocalLibrary(initialWorkspace)

export const useStoryStore = create<StoryState>((set, get) => ({
  workspace: initialWorkspace,
  project: restored.projects[restored.activeId],
  projects: restored.projects,
  dirty: false,
  hydrated: false,
  loading: false,
  saveError: null,
  loadWorkspace: async rawWorkspace => {
    const workspace = safeWorkspace(rawWorkspace)
    const previous = get()
    if (workspace === previous.workspace && (previous.hydrated || previous.loading)) return

    try {
      persistLocalLibrary(previous.workspace, previous.project, previous.projects)
    } catch {
      // The visible story remains exportable even if browser storage is full.
    }

    // Flush the previous workspace before changing the active in-memory
    // library; otherwise the debounce below could be cancelled by a fast
    // workspace switch.
    if (previous.hydrated && workspace !== previous.workspace) {
      try {
        const previousLibrary = buildLibrary(previous.project, previous.projects)
        await api.saveStoryLibrary(previous.workspace, previousLibrary)
        lastPersistedLibrary.set(previous.workspace, JSON.stringify(previousLibrary))
      } catch {
        // Its local cache remains intact and will be retried next time.
      }
    }

    const local = restoreLocalLibrary(workspace)
    set({
      workspace,
      project: local.projects[local.activeId],
      projects: local.projects,
      dirty: false,
      hydrated: false,
      loading: true,
      saveError: null,
    })
    try {
      const remoteValue = await api.fetchStoryLibrary(workspace)
      if (get().workspace !== workspace) return
      let library = normalizeLibrary(remoteValue)
      if (!library) {
        // First-run migration: upload the existing v2/legacy browser cache.
        library = local
        await api.saveStoryLibrary(workspace, library)
      }
      persistLocalLibrary(
        workspace,
        library.projects[library.activeId],
        library.projects,
      )
      lastPersistedLibrary.set(workspace, JSON.stringify(library))
      set({
        project: library.projects[library.activeId],
        projects: library.projects,
        dirty: false,
        hydrated: true,
        loading: false,
        saveError: null,
      })
      if (workspace === 'default') {
        window.localStorage.removeItem(LEGACY_AUTOSAVE_KEY)
      }
    } catch (error) {
      if (get().workspace !== workspace) return
      set({
        hydrated: false,
        loading: false,
        saveError: error instanceof Error ? error.message : 'Story Lab storage is unavailable',
      })
    }
  },
  setProject: value => set(state => {
    const project = normalizeStoryProject(value)
    return {
      project,
      projects: { ...state.projects, [project.id]: project },
      dirty: true,
    }
  }),
  patchProject: patch => set(state => {
    const project = touched(state.project, { ...state.project, ...patch })
    return {
      project,
      projects: { ...state.projects, [project.id]: project },
      dirty: true,
    }
  }),
  updateProject: updater => set(state => {
    const project = touched(state.project, updater(structuredClone(state.project)))
    return {
      project,
      projects: { ...state.projects, [project.id]: project },
      dirty: true,
    }
  }),
  newProject: projectType => set(state => {
    const fresh = createStoryProject(projectType)
    // New projects inherit the production profile. Keep the dormant explicit
    // provider values for a later opt-out, but never copy the previous Story's
    // inheritance mode or video override into a brand-new project.
    const project = {
      ...fresh,
      provider: { ...fresh.provider, ...state.project.provider, useGlobalProfile: true },
    }
    return {
      project,
      projects: { ...state.projects, [project.id]: project },
      dirty: true,
    }
  }),
  duplicateProject: id => set(state => {
    const source = state.projects[id || state.project.id]
    if (!source) return state
    const now = new Date().toISOString()
    const project = normalizeStoryProject({
      ...structuredClone(source),
      id: `story-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`,
      title: `${source.title} copy`,
      revision: 1,
      approvals: {},
      productions: [],
      createdAt: now,
      updatedAt: now,
    })
    return {
      project,
      projects: { ...state.projects, [project.id]: project },
      dirty: true,
    }
  }),
  openProject: id => set(state => {
    const project = state.projects[id]
    return project ? { project, dirty: true } : state
  }),
  deleteProject: id => set(state => {
    if (!state.projects[id]) return state
    const projects = { ...state.projects }
    delete projects[id]
    const remainingId = Object.keys(projects)[0]
    if (remainingId) {
      return {
        projects,
        project: state.project.id === id ? projects[remainingId] : state.project,
        dirty: true,
      }
    }
    const project = createStoryProject()
    return { projects: { [project.id]: project }, project, dirty: true }
  }),
}))

let saveTimer: number | undefined
let backendSaveChain: Promise<void> = Promise.resolve()
const lastPersistedLibrary = new Map<string, string>()
useStoryStore.subscribe(state => {
  if (typeof window === 'undefined') return
  try {
    persistLocalLibrary(state.workspace, state.project, state.projects)
  } catch {
    // Storypack export remains available when browser storage is full.
  }
  if (!state.hydrated) return

  const workspace = state.workspace
  const library = buildLibrary(state.project, state.projects)
  const serialized = JSON.stringify(library)
  if (lastPersistedLibrary.get(workspace) === serialized) return

  window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    backendSaveChain = backendSaveChain
      .catch(() => undefined)
      .then(async () => {
        await api.saveStoryLibrary(workspace, library)
        lastPersistedLibrary.set(workspace, serialized)
        useStoryStore.setState(current => {
          if (
            current.workspace !== workspace
            || JSON.stringify(buildLibrary(current.project, current.projects)) !== serialized
          ) return {}
          return { dirty: false, saveError: null }
        })
      })
      .catch(error => {
        useStoryStore.setState(current => current.workspace === workspace
          ? {
              dirty: true,
              saveError: error instanceof Error ? error.message : 'Story Lab autosave failed',
            }
          : {})
      })
  }, 750)
})

export { createStoryProject, normalizeStoryProject, storyId } from './model'
