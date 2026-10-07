import type { ExportResult, Game, GameLibrary, ListReport, ProduceJob, StylePreset, StyleReference } from '../features/game-assets/types'

type FetchLike = typeof fetch

let transport: FetchLike = globalThis.fetch.bind(globalThis)

/** Tests replace the transport. Passing null restores `fetch`. */
export function setGameFetch(fetchImpl: FetchLike | null): void {
  transport = fetchImpl || globalThis.fetch.bind(globalThis)
}

export class GameRevisionConflict extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'GameRevisionConflict'
  }
}

async function gameResponse<T>(responsePromise: Promise<Response>, fallback: string): Promise<T> {
  const response = await responsePromise
  if (response.status === 204) return undefined as T
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown }
    const detail = body.detail
    const message = typeof detail === 'object' && detail && 'message' in detail
      ? String((detail as { message?: unknown }).message || '')
      : typeof detail === 'string' ? detail : ''
    if (response.status === 409) throw new GameRevisionConflict(message || fallback)
    throw new Error(message || fallback)
  }
  return response.json() as Promise<T>
}

function send(path: string, method: string, body?: unknown): Promise<Response> {
  return transport(path, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function fetchGamePresets(): Promise<{ presets: StylePreset[]; actions: unknown[] }> {
  return gameResponse(send('/api/v1/games/presets', 'GET'), 'Could not load game presets')
}

export function fetchGameLibrary(workspace: string): Promise<GameLibrary> {
  return gameResponse(send(`/api/v1/games?workspace=${encodeURIComponent(workspace)}`, 'GET'), 'Could not load games')
}

export function fetchGame(workspace: string, gameId: string): Promise<Game> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}?workspace=${encodeURIComponent(workspace)}`, 'GET'), 'Could not load the game')
}

export function createGame(workspace: string, game: Record<string, unknown>): Promise<Game> {
  return gameResponse(send('/api/v1/games', 'POST', { workspace, game }), 'Could not create the game')
}

export function updateGame(workspace: string, gameId: string, patch: Record<string, unknown>, baseRevision: number): Promise<Game> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}`, 'PUT', {
    workspace, patch, base_revision: baseRevision,
  }), 'Could not save the game')
}

export function deleteGame(workspace: string, gameId: string): Promise<void> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}?workspace=${encodeURIComponent(workspace)}`, 'DELETE'), 'Could not delete the game')
}

export function approveGameStyle(workspace: string, gameId: string, baseRevision: number, references: StyleReference[]): Promise<Game> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/style/approve`, 'POST', {
    workspace,
    base_revision: baseRevision,
    references: references.map(item => ({ asset_id: item.assetId, attempt_id: item.attemptId })),
  }), 'Could not approve the style')
}

export function updateGameAsset(workspace: string, gameId: string, assetId: string, patch: Record<string, unknown>, baseRevision: number): Promise<unknown> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/assets/${encodeURIComponent(assetId)}`, 'PATCH', {
    workspace, patch, base_revision: baseRevision,
  }), 'Could not update the asset')
}

export function approveGameAttempt(workspace: string, gameId: string, assetId: string, attemptId: string, baseRevision: number): Promise<unknown> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/assets/${encodeURIComponent(assetId)}/approve`, 'POST', {
    workspace, attempt_id: attemptId, base_revision: baseRevision,
  }), 'Could not approve the attempt')
}

export function rejectGameAttempt(workspace: string, gameId: string, assetId: string, attemptId: string, note: string, baseRevision: number): Promise<unknown> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/assets/${encodeURIComponent(assetId)}/reject`, 'POST', {
    workspace, attempt_id: attemptId, note, base_revision: baseRevision,
  }), 'Could not reject the attempt')
}

export function lockGameAsset(workspace: string, gameId: string, assetId: string, locked: boolean, baseRevision: number): Promise<unknown> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/assets/${encodeURIComponent(assetId)}/lock`, 'POST', {
    workspace, locked, base_revision: baseRevision,
  }), 'Could not lock the asset')
}

export function exportGame(workspace: string, gameId: string): Promise<ExportResult> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/export`, 'POST', { workspace }), 'Could not export the game')
}

export function gameAssetsFromList(workspace: string, gameId: string, body: { text?: string; csv?: string; items?: unknown[]; format?: string; check?: boolean; replace?: boolean }): Promise<ListReport> {
  const payload: Record<string, unknown> = { workspace, check: Boolean(body.check), replace: Boolean(body.replace) }
  if (body.items) payload.items = body.items
  else if (body.format === 'csv') payload.csv = body.csv || body.text || ''
  else payload.text = body.text || ''
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/assets/from-list`, 'POST', payload), 'Could not read the asset list')
}

function asJob(job: ProduceJob & { jobId?: string }): ProduceJob {
  return { ...job, id: job.id || job.jobId || '' }
}

export async function produceGame(workspace: string, gameId: string, body: { assetIds?: string[]; kinds?: string[]; rerender?: boolean; candidates?: number } = {}): Promise<ProduceJob> {
  const payload: Record<string, unknown> = { workspace, rerender: Boolean(body.rerender) }
  if (body.assetIds) payload.asset_ids = body.assetIds
  if (body.kinds) payload.kinds = body.kinds
  if (body.candidates) payload.candidates = body.candidates
  return asJob(await gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/produce`, 'POST', payload), 'Could not start production'))
}

export async function fetchProduceJob(workspace: string, jobId: string): Promise<ProduceJob> {
  return asJob(await gameResponse(send(`/api/v1/games/produce/jobs/${encodeURIComponent(jobId)}?workspace=${encodeURIComponent(workspace)}`, 'GET'), 'Could not read the produce job'))
}

export async function cancelProduceJob(workspace: string, jobId: string): Promise<ProduceJob> {
  return asJob(await gameResponse(send(`/api/v1/games/produce/jobs/${encodeURIComponent(jobId)}/cancel`, 'POST', { workspace }), 'Could not cancel production'))
}

export async function resumeProduceJob(workspace: string, jobId: string): Promise<ProduceJob> {
  return asJob(await gameResponse(send(`/api/v1/games/produce/jobs/${encodeURIComponent(jobId)}/resume`, 'POST', { workspace }), 'Could not resume production'))
}

export async function startStyleSheet(workspace: string, gameId: string): Promise<ProduceJob> {
  return asJob(await gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/style/sheet`, 'POST', { workspace }), 'Could not start the style sheet'))
}
