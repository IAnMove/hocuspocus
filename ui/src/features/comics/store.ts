import { create } from 'zustand'
import { createComicPage, createComicProject } from './model'
import type { ComicAsset, ComicElement, ComicPage, ComicProject } from './types'

type Snapshot = { past: ComicProject[]; future: ComicProject[] }

interface ComicState {
  project: ComicProject
  persistedName: string | null
  currentPageId: string
  selectedId: string | null
  zoom: number
  dirty: boolean
  history: Snapshot
  setProject: (project: ComicProject, persistedName?: string | null) => void
  patchProject: (patch: Partial<ComicProject>) => void
  setPersistedName: (name: string | null) => void
  setCurrentPage: (id: string) => void
  setSelected: (id: string | null) => void
  setZoom: (zoom: number) => void
  addPage: () => void
  duplicatePage: (id: string) => void
  deletePage: (id: string) => void
  updatePage: (id: string, patch: Partial<ComicPage>) => void
  addElement: (pageId: string, element: ComicElement) => void
  updateElement: (pageId: string, elementId: string, patch: Partial<ComicElement>, record?: boolean) => void
  removeElement: (pageId: string, elementId: string) => void
  addAsset: (asset: ComicAsset) => void
  markSaved: () => void
  commitSnapshot: (snapshot: ComicProject) => void
  undo: () => void
  redo: () => void
}

const clone = <T,>(value: T): T => structuredClone(value)

function withHistory(state: ComicState, project: ComicProject) {
  return {
    project: { ...project, updatedAt: new Date().toISOString() },
    history: {
      past: [...state.history.past.slice(-39), clone(state.project)],
      future: [],
    },
    dirty: true,
  }
}

export const useComicStore = create<ComicState>((set) => {
  const project = createComicProject()
  return {
    project,
    persistedName: null,
    currentPageId: project.pages[0].id,
    selectedId: null,
    zoom: 0.65,
    dirty: false,
    history: { past: [], future: [] },

    setProject: (next, persistedName = null) => set({
      project: clone(next),
      persistedName,
      currentPageId: next.pages[0]?.id ?? '',
      selectedId: null,
      dirty: false,
      history: { past: [], future: [] },
    }),
    patchProject: patch => set(state => withHistory(state, { ...state.project, ...patch })),
    setPersistedName: persistedName => set({ persistedName }),
    setCurrentPage: currentPageId => set({ currentPageId, selectedId: null }),
    setSelected: selectedId => set({ selectedId }),
    setZoom: zoom => set({ zoom: Math.min(1.5, Math.max(0.2, zoom)) }),

    addPage: () => set(state => {
      const page = createComicPage(state.project.format.width, state.project.format.height)
      return {
        ...withHistory(state, { ...state.project, pages: [...state.project.pages, page] }),
        currentPageId: page.id,
        selectedId: null,
      }
    }),
    duplicatePage: id => set(state => {
      const source = state.project.pages.find(page => page.id === id)
      if (!source) return state
      const page = clone(source)
      page.id = `${source.id}-copy-${Date.now().toString(36)}`
      page.elements = page.elements.map(el => ({
        ...el,
        id: `${el.id}-copy-${crypto.randomUUID().slice(0, 5)}`,
      }))
      return {
        ...withHistory(state, { ...state.project, pages: [...state.project.pages, page] }),
        currentPageId: page.id,
        selectedId: null,
      }
    }),
    deletePage: id => set(state => {
      if (state.project.pages.length <= 1) return state
      const pages = state.project.pages.filter(page => page.id !== id)
      return {
        ...withHistory(state, { ...state.project, pages }),
        currentPageId: state.currentPageId === id ? pages[0].id : state.currentPageId,
        selectedId: null,
      }
    }),
    updatePage: (id, patch) => set(state => withHistory(state, {
      ...state.project,
      pages: state.project.pages.map(page => page.id === id ? { ...page, ...patch } : page),
    })),
    addElement: (pageId, element) => set(state => ({
      ...withHistory(state, {
        ...state.project,
        pages: state.project.pages.map(page => page.id === pageId
          ? { ...page, elements: [...page.elements, element] }
          : page),
      }),
      selectedId: element.id,
    })),
    updateElement: (pageId, elementId, patch, record = false) => set(state => {
      const project = {
        ...state.project,
        updatedAt: new Date().toISOString(),
        pages: state.project.pages.map(page => page.id === pageId
          ? {
              ...page,
              elements: page.elements.map(element => element.id === elementId
                ? { ...element, ...patch } as ComicElement
                : element),
            }
          : page),
      }
      return record ? withHistory(state, project) : { project, dirty: true }
    }),
    removeElement: (pageId, elementId) => set(state => ({
      ...withHistory(state, {
        ...state.project,
        pages: state.project.pages.map(page => page.id === pageId
          ? {
              ...page,
              elements: page.elements.filter(element =>
                element.id !== elementId && element.parentId !== elementId),
            }
          : page),
      }),
      selectedId: state.selectedId === elementId ? null : state.selectedId,
    })),
    addAsset: asset => set(state => withHistory(state, {
      ...state.project,
      assets: { ...state.project.assets, [asset.id]: asset },
    })),
    markSaved: () => set({ dirty: false }),
    commitSnapshot: snapshot => set(state => ({
      history: {
        past: [...state.history.past.slice(-39), clone(snapshot)],
        future: [],
      },
      dirty: true,
    })),
    undo: () => set(state => {
      const previous = state.history.past.at(-1)
      if (!previous) return state
      return {
        project: clone(previous),
        history: {
          past: state.history.past.slice(0, -1),
          future: [clone(state.project), ...state.history.future.slice(0, 39)],
        },
        currentPageId: previous.pages.some(page => page.id === state.currentPageId)
          ? state.currentPageId
          : previous.pages[0].id,
        selectedId: null,
        dirty: true,
      }
    }),
    redo: () => set(state => {
      const next = state.history.future[0]
      if (!next) return state
      return {
        project: clone(next),
        history: {
          past: [...state.history.past, clone(state.project)],
          future: state.history.future.slice(1),
        },
        currentPageId: next.pages.some(page => page.id === state.currentPageId)
          ? state.currentPageId
          : next.pages[0].id,
        selectedId: null,
        dirty: true,
      }
    }),
  }
})
