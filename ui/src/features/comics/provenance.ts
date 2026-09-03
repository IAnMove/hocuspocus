import type { SeriesEpisode, SeriesLibrary, SeriesProject } from '../series/types'
import type { ComicDirectorRequest, ComicProject, ComicProvenance } from './types'

/** Browser-only handoff envelope used to restore the exact staged Comic. */
export const COMIC_HANDOFF_STORAGE_KEY = 'hocuspocus-comic-handoff-v1'

/** Remove one-shot handoffs after a project has consumed them. */
export function clearStagedComicHandoffs(clearPlanResult = false): void {
  if (typeof window === 'undefined') return
  try {
    if (clearPlanResult) window.localStorage.removeItem('maestro-last-comic-plan-result')
    window.localStorage.removeItem('maestro-story-comic-draft')
    window.localStorage.removeItem('maestro-story-comic-auto-start')
    window.localStorage.removeItem(COMIC_HANDOFF_STORAGE_KEY)
  } catch {
    // Private browsing may block storage; the in-memory project remains valid.
  }
}

/**
 * Read the browser handoff without guessing which Comic is current. The
 * caller supplies the current project ID; a mismatched handoff falls through
 * to the legacy Story key for backwards compatibility.
 */
export function readStagedComicDirectorRequest(
  projectId: string | undefined,
  defaults: ComicDirectorRequest,
): ComicDirectorRequest | null {
  if (typeof window === 'undefined') return null
  try {
    const handoff = JSON.parse(window.localStorage.getItem(COMIC_HANDOFF_STORAGE_KEY) || 'null')
    if (
      handoff && typeof handoff === 'object'
      && (!projectId || handoff.projectId === projectId)
      && handoff.request && typeof handoff.request === 'object'
    ) return { ...defaults, ...handoff.request }
    const staged = JSON.parse(window.localStorage.getItem('maestro-story-comic-draft') || 'null')
    if (!staged || typeof staged !== 'object') return null
    return { ...defaults, ...staged }
  } catch {
    return null
  }
}

export interface SeriesComicSourceIdentity {
  workspaceId: string
  seriesId: string
  episodeId: string
}

export class ComicSourceResolutionError extends Error {
  readonly code: 'workspace_mismatch' | 'series_not_found' | 'episode_not_found' | 'comic_mismatch'

  constructor(
    message: string,
    code: ComicSourceResolutionError['code'],
  ) {
    super(message)
    this.name = 'ComicSourceResolutionError'
    this.code = code
  }
}

/**
 * Resolve a Series episode by immutable IDs. Titles are intentionally not
 * considered: two projects or episodes may legitimately share a title.
 */
export function resolveSeriesEpisodeById(
  library: SeriesLibrary,
  source: SeriesComicSourceIdentity,
): { series: SeriesProject; episode: SeriesEpisode } {
  if (library.workspaceId !== source.workspaceId) {
    throw new ComicSourceResolutionError(
      `Series source belongs to workspace “${source.workspaceId}”, not “${library.workspaceId}”.`,
      'workspace_mismatch',
    )
  }
  const series = library.seriesById[source.seriesId]
  if (!series) {
    throw new ComicSourceResolutionError(
      `Series source ID “${source.seriesId}” is not present in workspace “${source.workspaceId}”.`,
      'series_not_found',
    )
  }
  const episode = series.episodesById[source.episodeId]
  if (!episode) {
    throw new ComicSourceResolutionError(
      `Episode source ID “${source.episodeId}” is not present in Series “${series.title}”.`,
      'episode_not_found',
    )
  }
  return { series, episode }
}

/**
 * Validate and restore a Series-derived Comic's source relation. A normal
 * standalone Comic has no source and returns null; a malformed or deleted
 * source throws so callers can surface a recovery error instead of selecting
 * a similarly named project.
 */
export function resolveComicSource(
  project: ComicProject,
  library: SeriesLibrary,
  workspaceId = project.provenance?.workspaceId || library.workspaceId,
): { provenance: ComicProvenance; series: SeriesProject; episode: SeriesEpisode } | null {
  const provenance = project.provenance
  if (!provenance) return null
  if (provenance.destination.comicId !== project.id) {
    throw new ComicSourceResolutionError(
      `Comic provenance points to “${provenance.destination.comicId}”, not “${project.id}”.`,
      'comic_mismatch',
    )
  }
  if (provenance.workspaceId !== workspaceId) {
    throw new ComicSourceResolutionError(
      `Comic provenance belongs to workspace “${provenance.workspaceId}”, not “${workspaceId}”.`,
      'workspace_mismatch',
    )
  }
  const resolved = resolveSeriesEpisodeById(library, {
    workspaceId,
    seriesId: provenance.source.seriesId,
    episodeId: provenance.source.episodeId,
  })
  return { provenance, ...resolved }
}
