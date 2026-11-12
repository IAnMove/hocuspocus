import { create } from 'zustand'
import { safeStorageGet, safeStorageSet } from '../../../lib/safeStorage'

/**
 * The Validation tab's open shot and the inspector's unsaved section edits, per episode. Kept in session storage so a
 * trip to an editor (Video 2D, Video 3D, the character's face rig) comes back to the same shot with the same drafts.
 */
export type SectionKey = 'plan' | 'cast' | 'cast3d' | 'lines' | 'set' | 'props' | 'fx' | 'sfx' | 'sound' | 'card' | 'scene3d' | 'video'
export type SectionDraft = Record<string, unknown>

interface EpisodeInspector {
  openShotId: string
  drafts: Record<string, Partial<Record<SectionKey, SectionDraft>>>
  /** When each shot was last edited here (ms), to say its take is older than its plan. */
  edited: Record<string, number>
}

interface InspectorState {
  episodes: Record<string, EpisodeInspector>
}

const STORAGE_KEY = 'hocuspocus:series-shot-inspector'
const EMPTY: EpisodeInspector = { openShotId: '', drafts: {}, edited: {} }

function restored(): InspectorState {
  try {
    const value = JSON.parse(safeStorageGet('session', STORAGE_KEY) || 'null')
    return value && typeof value === 'object' && value.episodes && typeof value.episodes === 'object' ? value as InspectorState : { episodes: {} }
  } catch { return { episodes: {} } }
}

export const useShotInspector = create<InspectorState>(() => restored())

useShotInspector.subscribe(state => { safeStorageSet('session', STORAGE_KEY, JSON.stringify(state)) })

export const inspectorKey = (workspace: string, seriesId: string, episodeId: string) => `${workspace}/${seriesId}/${episodeId}`

function change(key: string, update: (current: EpisodeInspector) => EpisodeInspector) {
  useShotInspector.setState(state => ({ episodes: { ...state.episodes, [key]: update(state.episodes[key] || EMPTY) } }))
}

export function episodeInspector(key: string): EpisodeInspector {
  return useShotInspector.getState().episodes[key] || EMPTY
}

export function useEpisodeInspector(key: string): EpisodeInspector {
  return useShotInspector(state => state.episodes[key]) || EMPTY
}

export function openInspectorShot(key: string, shotId: string) {
  change(key, current => ({ ...current, openShotId: shotId }))
}

export function setSectionDraft(key: string, shotId: string, section: SectionKey, draft: SectionDraft | undefined) {
  change(key, current => {
    const own = { ...(current.drafts[shotId] || {}) }
    if (draft === undefined) delete own[section]; else own[section] = draft
    const drafts = { ...current.drafts }
    if (Object.keys(own).length) drafts[shotId] = own; else delete drafts[shotId]
    return { ...current, drafts }
  })
}

export function markShotEdited(key: string, shotId: string, at: number) {
  change(key, current => ({ ...current, edited: { ...current.edited, [shotId]: at } }))
}
