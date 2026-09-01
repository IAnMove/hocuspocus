import type { SeriesAssemblyActionRequest, SeriesAssemblyDiscardResponse, SeriesAssemblyJob, SeriesAssemblyRecoveryResponse, SeriesAssemblyStartRequest } from '../features/series/assemblyContract'
import { BASE } from './http'

async function seriesResponse<T>(responsePromise: Response | Promise<Response>, fallback: string): Promise<T> {
  const response = await responsePromise
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: fallback }))
    const detailMessage = typeof error.detail === 'object' && error.detail
      ? error.detail.message
      : error.detail
    throw new Error(detailMessage || error.error || fallback)
  }
  return response.json() as Promise<T>
}

export class SeriesEpisodeRevisionError extends Error {
  readonly currentSeriesRevision: number
  readonly currentEpisodeUpdatedAt: string

  constructor(message: string, currentSeriesRevision: number, currentEpisodeUpdatedAt: string) {
    super(message)
    this.name = 'SeriesEpisodeRevisionError'
    this.currentSeriesRevision = currentSeriesRevision
    this.currentEpisodeUpdatedAt = currentEpisodeUpdatedAt
  }
}

export async function fetchSeriesLibrary(workspace: string): Promise<import('../features/series/types').SeriesLibrary> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/library?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not load Series Lab library')
}

export async function fetchSeriesProject(
  workspace: string,
  seriesId: string,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not load Series Lab project')
}

export async function createSeriesProject(
  workspace: string,
  title = 'Untitled series',
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(`${BASE}/api/v1/series`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, title }),
  }), 'Could not create Series Lab project')
}

export async function saveSeriesProject(
  workspace: string,
  project: import('../features/series/types').SeriesProject,
  baseRevision: number,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(`${BASE}/api/v1/series/${encodeURIComponent(project.id)}`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, series: project, baseRevision }),
  }), 'Could not save Series Lab project')
}

export async function deleteSeriesProject(workspace: string, seriesId: string): Promise<void> {
  await seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}?workspace=${encodeURIComponent(workspace)}`,
    { method: 'DELETE' },
  ), 'Could not delete Series Lab project')
}

export async function duplicateSeriesProject(
  workspace: string,
  seriesId: string,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(`${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/duplicate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace }),
  }), 'Could not duplicate Series Lab project')
}

export async function importStoryAsSeries(
  workspace: string,
  storyId: string,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(`${BASE}/api/v1/series/import-story`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, storyId }),
  }), 'Could not import Story Lab project')
}

export async function createSeriesEpisode(
  workspace: string,
  seriesId: string,
  seasonId?: string,
  episode?: Partial<Pick<import('../features/series/types').SeriesEpisode,
    'title' | 'premise' | 'logline' | 'targetDurationSeconds' | 'status' | 'outline'>>,
): Promise<import('../features/series/types').SeriesEpisode> {
  return seriesResponse(fetch(`${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ workspace, seasonId, episode }),
  }), 'Could not create Series episode')
}

export async function fetchSeriesEpisodes(
  workspace: string, seriesId: string,
): Promise<{ episodes: import('../features/series/types').SeriesEpisode[] }> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not list Series episodes')
}

export async function fetchSeriesEpisode(
  workspace: string, seriesId: string, episodeId: string,
): Promise<import('../features/series/types').SeriesEpisode> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not load Series episode')
}

export async function deleteSeriesEpisode(
  workspace: string, seriesId: string, episodeId: string,
): Promise<void> {
  await seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}?workspace=${encodeURIComponent(workspace)}`,
    { method: 'DELETE' },
  ), 'Could not delete Series episode')
}

export async function importSeriesAsset(
  workspace: string,
  seriesId: string,
  input: {
    uploadPath: string
    name: string
    ownerType: 'series' | 'character' | 'location' | 'prop' | 'episode' | 'shot'
    ownerId: string
    kind?: import('../features/series/types').SeriesAsset['kind']
    referenceRole?: string
    metadata?: Record<string, unknown>
  },
): Promise<{
  asset: import('../features/series/types').SeriesAsset
  series: import('../features/series/types').SeriesProject
}> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/assets/import`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, ...input }),
    },
  ), 'Could not import Series reference')
}

export async function saveSeriesEpisode(
  workspace: string,
  seriesId: string,
  episode: import('../features/series/types').SeriesEpisode,
  concurrency: { baseSeriesRevision?: number; baseEpisodeUpdatedAt?: string },
): Promise<import('../features/series/types').SeriesEpisode> {
  const response = await fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episode.id)}`,
    {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, episode, ...concurrency }),
    },
  )
  if (response.status === 409) {
    const payload = await response.json().catch(() => null)
    const detail = payload?.detail
    throw new SeriesEpisodeRevisionError(
      (typeof detail === 'object' && detail?.message) || 'Episode changed; reload before saving',
      Number(detail?.currentSeriesRevision || 0),
      String(detail?.currentEpisodeUpdatedAt || ''),
    )
  }
  return seriesResponse(response, 'Could not save Series episode')
}

export async function startSeriesPlan(
  workspace: string,
  seriesId: string,
  episodeId: string,
  options: {
    scope: 'outline' | 'script' | 'shots' | 'complete'
    instruction?: string
    writingProvider?: string
    writingModel?: string
    writingBaseUrl?: string
  },
): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/plan/start`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, ...options }),
    },
  ), 'Could not start Series episode planning')
}

export async function startSeriesCanonPreparation(
  workspace: string,
  seriesId: string,
  options: {
    instruction?: string
    writingProvider?: string
    writingModel?: string
    writingBaseUrl?: string
    generateImages?: boolean
    bootstrapKnownSeries?: boolean
    autoApply?: boolean
  },
): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/canon/prepare/start`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, ...options }),
    },
  ), 'Could not prepare Series canon')
}

export async function fetchSeriesPlanJob(
  jobId: string,
  signal?: AbortSignal,
): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}`,
    signal ? { signal } : undefined,
  ), 'Could not read Series planning job')
}

export async function cancelSeriesPlanJob(jobId: string): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' },
  ), 'Could not cancel Series planning job')
}

export async function resumeSeriesPlanJob(jobId: string): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}/resume`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
    },
  ), 'Could not resume Series planning job')
}

export async function applySeriesPlanJob(
  jobId: string,
  episodeResult?: import('../features/series/types').SeriesEpisode,
): Promise<import('../features/series/types').SeriesEpisode> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}/apply`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(episodeResult ? { episodeResult } : {}),
    },
  ), 'Could not apply Series planning proposal')
}

export async function applySeriesCanonPlanJob(jobId: string): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}/apply-canon`, { method: 'POST' },
  ), 'Could not apply Series canon proposal')
}

export async function approveSeriesCanon(
  workspace: string, seriesId: string, baseRevision: number,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/canon/approve`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, baseRevision }),
    },
  ), 'Could not approve Series canon')
}

export async function fetchSeriesPlanRecovery(workspace: string): Promise<{ jobs: import('../features/series/types').SeriesJobStatus[] }> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/recovery?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not read Series planning recovery')
}

export async function discardSeriesPlanJob(jobId: string): Promise<void> {
  await seriesResponse(fetch(
    `${BASE}/api/v1/series/plan/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' },
  ), 'Could not discard Series planning job')
}

export async function routeSeriesReferences(
  workspace: string,
  seriesId: string,
  episodeId: string,
  shotId?: string,
): Promise<{ shotId?: string; manifest?: import('../features/series/types').SeriesReferenceManifest; manifests?: Record<string, import('../features/series/types').SeriesReferenceManifest> }> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/references/route`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, shotId }),
    },
  ), 'Could not route Series references')
}

export async function previewSeriesShotDuration(
  workspace: string,
  seriesId: string,
  shot: import('../features/series/types').SeriesShot,
  signal?: AbortSignal,
): Promise<import('../features/series/types').SeriesShot> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/shots/duration/preview`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
      body: JSON.stringify({ workspace, shot }),
    },
  ), 'Could not calculate Series dialogue duration')
}

export async function startSeriesRender(
  workspace: string,
  seriesId: string,
  episodeId: string,
  options: {
    mode: 'selected' | 'failed' | 'missing' | 'all'
    shotIds?: string[]
    seed?: number
    settings?: Record<string, unknown>
  },
): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/render/start`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, ...options }),
    },
  ), 'Could not start Series render')
}

export async function fetchSeriesRenderJob(jobId: string): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/render/jobs/${encodeURIComponent(jobId)}`,
  ), 'Could not read Series render job')
}

export async function cancelSeriesRenderJob(jobId: string): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/render/jobs/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' },
  ), 'Could not cancel Series render job')
}

export async function resumeSeriesRenderJob(jobId: string): Promise<import('../features/series/types').SeriesJobStatus> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/render/jobs/${encodeURIComponent(jobId)}/resume`, { method: 'POST' },
  ), 'Could not resume Series render job')
}

export async function fetchSeriesRenderRecovery(workspace: string): Promise<{ jobs: import('../features/series/types').SeriesJobStatus[] }> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/render/recovery?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not read Series render recovery')
}

export async function discardSeriesRenderJob(jobId: string): Promise<void> {
  await seriesResponse(fetch(
    `${BASE}/api/v1/series/render/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' },
  ), 'Could not discard Series render job')
}

export async function approveSeriesAttempt(
  workspace: string, seriesId: string, episodeId: string, shotId: string, attemptId: string,
): Promise<import('../features/series/types').SeriesShot> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/shots/${encodeURIComponent(shotId)}/attempts/${encodeURIComponent(attemptId)}/approve`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace }),
    },
  ), 'Could not approve Series shot attempt')
}

export async function approveSeriesAttemptsBulk(
  workspace: string,
  seriesId: string,
  episodeId: string,
  selections: Array<{ shotId: string; attemptId: string }>,
): Promise<{ seriesId: string; episodeId: string; revision: number; episode: import('../features/series/types').SeriesEpisode }> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/attempts/approve-bulk`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, selections }),
    },
  ), 'Could not approve Series shot attempts')
}

export async function startSeriesEpisodeAssembly(
  workspace: string, seriesId: string, episodeId: string,
): Promise<SeriesAssemblyJob> {
  const payload: SeriesAssemblyStartRequest = { workspace }
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/assembly/start`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  ), 'Could not start Series episode assembly')
}

export async function fetchSeriesEpisodeAssembly(
  jobId: string, workspace?: string,
): Promise<SeriesAssemblyJob> {
  const query = workspace ? `?workspace=${encodeURIComponent(workspace)}` : ''
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/assembly/jobs/${encodeURIComponent(jobId)}${query}`,
  ), 'Could not read Series episode assembly')
}

export async function cancelSeriesEpisodeAssembly(
  jobId: string, workspace: string,
): Promise<SeriesAssemblyJob> {
  const payload: SeriesAssemblyActionRequest = { workspace }
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/assembly/jobs/${encodeURIComponent(jobId)}/cancel`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ), 'Could not cancel Series episode assembly')
}

export async function resumeSeriesEpisodeAssembly(
  jobId: string, workspace: string,
): Promise<SeriesAssemblyJob> {
  const payload: SeriesAssemblyActionRequest = { workspace }
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/assembly/jobs/${encodeURIComponent(jobId)}/resume`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) },
  ), 'Could not resume Series episode assembly')
}

export async function discardSeriesEpisodeAssembly(
  jobId: string, workspace: string,
): Promise<SeriesAssemblyDiscardResponse> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/assembly/jobs/${encodeURIComponent(jobId)}?workspace=${encodeURIComponent(workspace)}`,
    { method: 'DELETE' },
  ), 'Could not discard Series episode assembly')
}

export async function fetchSeriesAssemblyRecovery(workspace: string): Promise<SeriesAssemblyRecoveryResponse> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/assembly/recovery?workspace=${encodeURIComponent(workspace)}`,
  ), 'Could not read Series assembly recovery')
}

export async function rejectSeriesAttempt(
  workspace: string, seriesId: string, episodeId: string, shotId: string, attemptId: string,
): Promise<import('../features/series/types').SeriesShot> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/shots/${encodeURIComponent(shotId)}/attempts/${encodeURIComponent(attemptId)}/reject`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace }),
    },
  ), 'Could not reject Series shot attempt')
}

export async function commitSeriesCanon(
  workspace: string,
  seriesId: string,
  episodeId: string,
  baseRevision: number,
  decisions: Record<string, 'pending' | 'accepted' | 'rejected'>,
): Promise<import('../features/series/types').SeriesProject> {
  return seriesResponse(fetch(
    `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/canon/commit`,
    {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace, baseRevision, decisions }),
    },
  ), 'Could not commit Series canon')
}
