import { create } from 'zustand'
import { changedSections, createStoryProject, normalizeStoryProject } from './model'
import type { StoryProject } from './types'

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

function restoreLibrary(workspace: string): StoryLibraryData {
  const fallback = createStoryProject()
  if (typeof window === 'undefined') {
    return { version: 2, activeId: fallback.id, projects: { [fallback.id]: fallback } }
  }
  try {
    const raw = JSON.parse(window.localStorage.getItem(libraryKey(workspace)) || 'null')
    if (raw && typeof raw === 'object' && raw.projects && typeof raw.projects === 'object') {
      const projects = Object.fromEntries(
        Object.values(raw.projects as Record<string, unknown>).map(value => {
          const project = normalizeStoryProject(value)
          return [project.id, project]
        }),
      )
      const firstId = Object.keys(projects)[0]
      if (firstId) {
        const activeId = typeof raw.activeId === 'string' && projects[raw.activeId]
          ? raw.activeId : firstId
        return { version: 2, activeId, projects }
      }
    }
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

function persistLibrary(
  workspace: string,
  project: StoryProject,
  projects: Record<string, StoryProject>,
): void {
  if (typeof window === 'undefined') return
  const complete = { ...projects, [project.id]: project }
  window.localStorage.setItem(libraryKey(workspace), JSON.stringify({
    version: 2,
    activeId: project.id,
    projects: complete,
  } satisfies StoryLibraryData))
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
  loadWorkspace: (workspace: string) => void
  setProject: (project: StoryProject) => void
  patchProject: (patch: Partial<StoryProject>) => void
  updateProject: (updater: (project: StoryProject) => StoryProject) => void
  newProject: () => void
  duplicateProject: (id?: string) => void
  openProject: (id: string) => void
  deleteProject: (id: string) => void
  markSaved: () => void
}

const initialWorkspace = 'default'
const restored = restoreLibrary(initialWorkspace)

export const useStoryStore = create<StoryState>((set) => ({
  workspace: initialWorkspace,
  project: restored.projects[restored.activeId],
  projects: restored.projects,
  dirty: false,
  loadWorkspace: workspace => set(state => {
    if (workspace === state.workspace) return state
    try {
      persistLibrary(state.workspace, state.project, state.projects)
    } catch {
      // The visible story remains exportable even if browser storage is full.
    }
    const library = restoreLibrary(workspace)
    return {
      workspace,
      project: library.projects[library.activeId],
      projects: library.projects,
      dirty: false,
    }
  }),
  setProject: value => set(state => {
    const project = normalizeStoryProject(value)
    return {
      project,
      projects: { ...state.projects, [project.id]: project },
      dirty: false,
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
  newProject: () => set(state => {
    const project = createStoryProject()
    return {
      project,
      projects: { ...state.projects, [project.id]: project },
      dirty: false,
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
    return project ? { project, dirty: false } : state
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
  markSaved: () => set({ dirty: false }),
}))

let saveTimer: number | undefined
useStoryStore.subscribe(state => {
  if (typeof window === 'undefined') return
  window.clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    try {
      persistLibrary(state.workspace, state.project, state.projects)
      window.localStorage.removeItem(LEGACY_AUTOSAVE_KEY)
    } catch {
      // Storypack export remains available when browser storage is full.
    }
  }, 250)
})

export { createStoryProject, normalizeStoryProject, storyId } from './model'
