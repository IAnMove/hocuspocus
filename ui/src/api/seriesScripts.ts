import { BASE } from './http'
import { SeriesRequestError } from './series'

/** Who sent a script: a person, an MCP agent, the Wizard or the server's own job. */
export type SeriesScriptAuthor = 'user' | 'agent' | 'wizard' | 'server'

/** One script `series.episode.from_script` wrote into an episode, as the server keeps it (services/series_script_history.py). */
export interface SeriesScriptRevision {
  revision: number
  submittedAt: string
  by: SeriesScriptAuthor
  tool: string
  /** The script created the episode (else it rewrote it). */
  created: boolean
  shots: number
  languages: string[]
  digest: string
  /** Times this exact script was written; the last one at `lastAppliedAt` by `lastBy`. */
  applied: number
  lastAppliedAt?: string
  lastBy?: SeriesScriptAuthor
  /** A rewrite from an older revision. */
  restoredFrom?: number
}

export interface SeriesScriptRecord extends SeriesScriptRevision {
  script: Record<string, unknown>
}

export interface SeriesScriptWriteReply {
  episodeId?: string
  checked?: boolean
  shots?: string[]
  scriptRevision?: number | null
  missingLines?: Record<string, string[]>
  removedShots?: string[]
}

function scriptsPath(seriesId: string, episodeId: string): string {
  return `${BASE}/api/v1/series/${encodeURIComponent(seriesId)}/episodes/${encodeURIComponent(episodeId)}/scripts`
}

async function scriptResponse<T>(response: Response, fallback: string): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: { message?: string; code?: string } | string }
    const detail = body.detail
    const message = typeof detail === 'string' ? detail : detail?.message
    throw new SeriesRequestError(message || fallback, response.status, typeof detail === 'object' ? detail?.code : undefined, detail)
  }
  return response.json() as Promise<T>
}

/** The scripts written into an episode, newest first (without the scripts themselves). */
export async function listSeriesEpisodeScripts(workspace: string, seriesId: string, episodeId: string, signal?: AbortSignal): Promise<SeriesScriptRevision[]> {
  const body = await scriptResponse<{ revisions?: SeriesScriptRevision[] }>(
    await fetch(`${scriptsPath(seriesId, episodeId)}?workspace=${encodeURIComponent(workspace)}`, { cache: 'no-store', signal }),
    'Could not list the episode scripts')
  return Array.isArray(body.revisions) ? body.revisions : []
}

/** One revision with its script exactly as it was sent. */
export async function getSeriesEpisodeScript(workspace: string, seriesId: string, episodeId: string, revision: number): Promise<SeriesScriptRecord> {
  return scriptResponse(await fetch(`${scriptsPath(seriesId, episodeId)}/${revision}?workspace=${encodeURIComponent(workspace)}`, { cache: 'no-store' }),
    'Could not read the script')
}

/** A link that downloads the script as a JSON file. */
export function seriesEpisodeScriptDownloadUrl(workspace: string, seriesId: string, episodeId: string, revision: number): string {
  return `${scriptsPath(seriesId, episodeId)}/${revision}?workspace=${encodeURIComponent(workspace)}&download=true`
}

/** Write the episode again from a kept script; `check` only checks it against the series as it is now. */
export async function rewriteSeriesEpisodeFromScript(workspace: string, seriesId: string, episodeId: string, revision: number,
  check = false): Promise<SeriesScriptWriteReply> {
  return scriptResponse(await fetch(`${scriptsPath(seriesId, episodeId)}/${revision}/rewrite`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspace, check }),
  }), 'Could not rewrite the episode')
}
