import { useEffect } from 'react'
import * as api from '../../api/client'
import type { ComicProject } from './types'
import { resolveComicSource } from './provenance'

/** Validate one project before an explicit history/import/open restore. */
export async function validateComicLineage(candidate: ComicProject): Promise<void> {
  if (!candidate.provenance) return
  const sourceWorkspace = candidate.provenance.workspaceId
  const library = await api.fetchSeriesLibrary(sourceWorkspace)
  resolveComicSource(candidate, library, sourceWorkspace)
}

/**
 * Check a restored Series-derived Comic against the authoritative Series
 * library. Missing IDs remain visible as a recovery error rather than being
 * replaced with a similarly named project.
 */
export function useComicLineageValidation(
  project: ComicProject,
  onError: (message: string) => void,
): void {
  useEffect(() => {
    if (!project.provenance) return
    let cancelled = false
    void validateComicLineage(project)
      .catch(error => {
        if (!cancelled) onError(error instanceof Error ? error.message : String(error))
      })
    return () => { cancelled = true }
    // The provenance IDs are the only inputs that can alter this resolution.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    project.id,
    project.provenance?.workspaceId,
    project.provenance?.source.seriesId,
    project.provenance?.source.episodeId,
  ])
}
