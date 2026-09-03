import type { SeriesEpisode, SeriesLibrary, SeriesProject } from '../series/types'
import type { ComicProject, ComicProvenance } from './types'

/** Browser-only handoff envelope used to restore the exact staged Comic. */
export const COMIC_HANDOFF_STORAGE_KEY = 'hocuspocus-comic-handoff-v1'

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
