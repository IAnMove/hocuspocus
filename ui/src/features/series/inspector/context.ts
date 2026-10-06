import { createContext } from 'react'
import type { SeriesShotScript } from '../../../api/seriesShotInspector'
import type { CharacterKitLibrary } from '../../../lib/characterKit'
import type { SeriesEpisode, SeriesProject, SeriesShot } from '../types'
import type { SectionDraft, SectionKey } from './inspectorStore'
import type { SaveChanges } from './InspectorSection'

/** What every part of the inspector reads: the shot (stored and as its script), its drafts and how to save a change. */
export interface PartContext {
  workspace: string
  series: SeriesProject
  episode: SeriesEpisode
  shot: SeriesShot
  script: SeriesShotScript | undefined
  /** inspectorKey of the episode, for the drafts. */
  inspector: string
  drafts: Partial<Record<SectionKey, SectionDraft>>
  save: SaveChanges
  /** The series' own language key of the lines (`spanish`...). */
  language: string
  kits: CharacterKitLibrary | null
}

export const sectionId = (shotId: string, part: string) => `series-inspector-${shotId}-${part}`

export function characterName(series: SeriesProject, id: unknown): string {
  return series.characters.find(item => item.id === id)?.name || String(id || '')
}

export function characterKit(series: SeriesProject, kits: CharacterKitLibrary | null, characterId: unknown) {
  const ref = series.characters.find(item => item.id === characterId)?.voiceProfile?.characterKitRef
  return ref ? kits?.kits[ref.id] : undefined
}

/** The inspector's "re-render this shot", offered again where a part was just saved (absent for a video take). */
export const RerenderShot = createContext<{ label: string; run: () => void; busy: boolean } | undefined>(undefined)
