import { create } from 'zustand'
import { safeStorageGet, safeStorageSet } from '../../lib/safeStorage'
import { comicId, createComicPage, createComicProject, normalizeComicProject } from './model'
import type { ComicAsset, ComicElement, ComicPage, ComicProject } from './types'

type Snapshot = { past: ComicProject[]; future: ComicProject[] }

interface ComicState {
  project: ComicProject
  persistedName: string | null
  currentPageId: string
  selectedId: string | null
  zoom: number
  snapEnabled: boolean
  dirty: boolean
  history: Snapshot
  setProject: (project: ComicProject, persistedName?: string | null) => void
  patchProject: (patch: Partial<ComicProject>) => void
  setPersistedName: (name: string | null) => void
  setCurrentPage: (id: string) => void
  setSelected: (id: string | null) => void
  setZoom: (zoom: number) => void
  setSnapEnabled: (enabled: boolean) => void
  addPage: () => void
  duplicatePage: (id: string) => void
  movePage: (id: string, delta: -1 | 1) => void
  deletePage: (id: string) => void
  updatePage: (id: string, patch: Partial<ComicPage>) => void
  addElement: (pageId: string, element: ComicElement) => void
  updateElement: (pageId: string, elementId: string, patch: Partial<ComicElement>, record?: boolean) => void
  reparentElement: (pageId: string, elementId: string) => void
  duplicateElement: (pageId: string, elementId: string) => void
  removeElement: (pageId: string, elementId: string) => void
  addAsset: (asset: ComicAsset) => void
  markSaved: () => void
  commitSnapshot: (snapshot: ComicProject) => void
  undo: () => void
  redo: () => void
}

const clone = <T,>(value: T): T => structuredClone(value)
const COMIC_AUTOSAVE_KEY = 'maestro-comic-autosave-v1'

function restoreAutosave(): {
  project: ComicProject
  persistedName: string | null
  currentPageId: string
} {
  const fallback = createComicProject()
  if (typeof window === 'undefined') {
    return { project: fallback, persistedName: null, currentPageId: fallback.pages[0].id }
  }
  try {
    const saved = JSON.parse(safeStorageGet('local', COMIC_AUTOSAVE_KEY) || 'null')
    const project = normalizeComicProject(saved?.project)
    const currentPageId = project.pages.some(page => page.id === saved?.currentPageId)
      ? saved.currentPageId
      : project.pages[0]?.id ?? ''
    return {
      project,
      persistedName: typeof saved?.persistedName === 'string' ? saved.persistedName : null,
      currentPageId,
    }
  } catch {
    return { project: fallback, persistedName: null, currentPageId: fallback.pages[0].id }
  }
}

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
  const restored = restoreAutosave()
  const project = restored.project
  return {
    project,
    persistedName: restored.persistedName,
    currentPageId: restored.currentPageId,
    selectedId: null,
    zoom: 0.65,
    snapEnabled: false,
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
    setZoom: zoom => set({ zoom: Math.min(3, Math.max(0.2, zoom)) }),
    setSnapEnabled: snapEnabled => set({ snapEnabled }),

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
      page.id = comicId('page')
      const ids = new Map(page.elements.map(element => [element.id, comicId(element.type)]))
      page.elements = page.elements.map(element => ({
        ...element,
        id: ids.get(element.id)!,
        parentId: element.parentId ? ids.get(element.parentId) ?? null : element.parentId,
      }))
      return {
        ...withHistory(state, { ...state.project, pages: [...state.project.pages, page] }),
        currentPageId: page.id,
        selectedId: null,
      }
    }),
    movePage: (id, delta) => set(state => {
      const index = state.project.pages.findIndex(page => page.id === id)
      const target = index + delta
      if (index < 0 || target < 0 || target >= state.project.pages.length) return state
      const pages = [...state.project.pages]
      const [page] = pages.splice(index, 1)
      pages.splice(target, 0, page)
      return withHistory(state, { ...state.project, pages })
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
    reparentElement: (pageId, elementId) => set(state => {
      const page = state.project.pages.find(item => item.id === pageId)
      const element = page?.elements.find(item => item.id === elementId)
      if (!page || !element || element.type === 'panel') return state
      const oldParent = element.parentId
        ? page.elements.find(item => item.id === element.parentId && item.type === 'panel')
        : undefined
      const absoluteX = element.x + (oldParent?.x ?? 0)
      const absoluteY = element.y + (oldParent?.y ?? 0)
      const centerX = absoluteX + element.width / 2
      const centerY = absoluteY + element.height / 2
      const target = page.elements
        .filter(item => item.type === 'panel')
        .sort((a, b) => b.zIndex - a.zIndex)
        .find(panel =>
          centerX >= panel.x && centerX <= panel.x + panel.width &&
          centerY >= panel.y && centerY <= panel.y + panel.height)
      const parentId = target?.id ?? null
      if (parentId === (element.parentId ?? null)) return state
      const project = {
        ...state.project,
        updatedAt: new Date().toISOString(),
        pages: state.project.pages.map(item => item.id !== pageId ? item : {
          ...item,
          elements: item.elements.map(child => child.id !== elementId ? child : {
            ...child,
            parentId,
            x: absoluteX - (target?.x ?? 0),
            y: absoluteY - (target?.y ?? 0),
          }),
        }),
      }
      return { project, dirty: true }
    }),
    duplicateElement: (pageId, elementId) => set(state => {
      const page = state.project.pages.find(item => item.id === pageId)
      const source = page?.elements.find(item => item.id === elementId)
      if (!page || !source) return state
      const copies: ComicElement[] = []
      const sourceIds = source.type === 'panel'
        ? [source.id, ...page.elements.filter(item => item.parentId === source.id).map(item => item.id)]
        : [source.id]
      const ids = new Map(sourceIds.map(id => [id, comicId('element')]))
      for (const id of sourceIds) {
        const original = page.elements.find(item => item.id === id)
        if (!original) continue
        copies.push({
          ...clone(original),
          id: ids.get(id)!,
          parentId: original.parentId === source.id ? ids.get(source.id)! : original.parentId,
          x: original.x + (original.id === source.id || source.type !== 'panel' ? 20 : 0),
          y: original.y + (original.id === source.id || source.type !== 'panel' ? 20 : 0),
        })
      }
      return {
        ...withHistory(state, {
          ...state.project,
          pages: state.project.pages.map(item => item.id === pageId
            ? { ...item, elements: [...item.elements, ...copies] }
            : item),
        }),
        selectedId: ids.get(source.id)!,
      }
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

if (typeof window !== 'undefined') {
  let autosaveTimer: number | undefined
  useComicStore.subscribe(state => {
    window.clearTimeout(autosaveTimer)
    autosaveTimer = window.setTimeout(() => {
      try {
        safeStorageSet('local', COMIC_AUTOSAVE_KEY, JSON.stringify({
          project: state.project,
          persistedName: state.persistedName,
          currentPageId: state.currentPageId,
          savedAt: new Date().toISOString(),
        }))
      } catch (error) {
        console.warn('[Comic autosave] Could not persist checkpoint:', error)
      }
    // Large comics contain many prompts and asset records. A longer debounce
    // avoids serialising the complete project on every drag frame or keystroke.
    }, 900)
  })
}
