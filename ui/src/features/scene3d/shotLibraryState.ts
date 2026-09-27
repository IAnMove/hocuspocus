import { SCENE3D_TEMPLATES, type Scene3DTemplateFilter, type Scene3DTemplateId } from './templates'
import { TEMPLATE_SETTINGS, type TemplateSetting } from './templateFilters'

/** Shot types in the library's sidebar, in the order people browse them. */
export const LIBRARY_CATEGORIES = ['pixel', 'animated', 'perspective', 'creative', 'dark-fantasy', 'psx', 'action', 'cinema', 'drive', 'space', 'music', 'product'] as const satisfies readonly Scene3DTemplateFilter[]

/** What the sidebar can show: recent shots, everything, one type, or the user's own scenarios. */
export type LibraryCategory = 'recent' | 'all' | 'mine' | typeof LIBRARY_CATEGORIES[number]
export type LibraryView = { category: LibraryCategory; setting: 'all' | TemplateSetting; query: string }

const RECENT_KEY = 'hocuspocus.shotLibrary.recent'
const VIEW_KEY = 'hocuspocus.shotLibrary.view'
const RECENT_LIMIT = 8
const KNOWN = new Set<string>(SCENE3D_TEMPLATES.map(item => item.id))
const CATEGORIES = new Set<string>(['recent', 'all', 'mine', ...LIBRARY_CATEGORIES])

function read(key: string): unknown {
  try { return JSON.parse(window.localStorage.getItem(key) ?? 'null') } catch { return null }
}

function write(key: string, value: unknown) {
  try { window.localStorage.setItem(key, JSON.stringify(value)) } catch { /* private window: the library still works */ }
}

/** Shots the user applied lately, newest first, dropping any that no longer exist. */
export function readRecentShots(): Scene3DTemplateId[] {
  const stored = read(RECENT_KEY)
  return Array.isArray(stored) ? stored.filter((id): id is Scene3DTemplateId => typeof id === 'string' && KNOWN.has(id)).slice(0, RECENT_LIMIT) : []
}

export function rememberRecentShot(id: Scene3DTemplateId): Scene3DTemplateId[] {
  const recent = [id, ...readRecentShots().filter(item => item !== id)].slice(0, RECENT_LIMIT)
  write(RECENT_KEY, recent)
  return recent
}

/** The category, set and search the library was left on, so it reopens there. */
export function readLibraryView(): LibraryView {
  const stored = read(VIEW_KEY) as Partial<LibraryView> | null
  const category = typeof stored?.category === 'string' && CATEGORIES.has(stored.category) ? stored.category as LibraryCategory : 'all'
  const setting = typeof stored?.setting === 'string' && (TEMPLATE_SETTINGS as readonly string[]).includes(stored.setting) ? stored.setting as TemplateSetting : 'all'
  return { category, setting, query: typeof stored?.query === 'string' ? stored.query.slice(0, 80) : '' }
}

export function saveLibraryView(view: LibraryView) {
  write(VIEW_KEY, view)
}

/** Where focus goes in a grid of `count` cards laid out in `columns` for an arrow, Home or End key. */
export function gridFocusTarget(index: number, key: string, count: number, columns: number): number | undefined {
  const steps: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -columns, ArrowDown: columns }
  if (key === 'Home') return 0
  if (key === 'End') return count - 1
  if (!(key in steps)) return undefined
  const next = index + steps[key]
  return next >= 0 && next < count ? next : index
}
