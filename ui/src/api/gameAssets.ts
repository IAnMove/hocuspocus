import type { ExportResult, Game, GameLibrary, GamePatch, GameProblem, ListReport, ProduceJob, StylePreset, StyleReference } from '../features/game-assets/types'

type FetchLike = typeof fetch

let transport: FetchLike = globalThis.fetch.bind(globalThis)

/** Tests replace the transport. Passing null restores `fetch`. */
export function setGameFetch(fetchImpl: FetchLike | null): void {
  transport = fetchImpl || globalThis.fetch.bind(globalThis)
}

/** A failed game request: the HTTP status, the server ``code`` and its ``problems``. */
export class GameApiError extends Error {
  readonly status: number
  readonly code: string
  readonly serverMessage: string
  readonly problems: GameProblem[]

  constructor(status: number, code: string, serverMessage: string, problems: GameProblem[] = []) {
    super(serverMessage || code || `HTTP ${status}`)
    this.name = 'GameApiError'
    this.status = status
    this.code = code
    this.serverMessage = serverMessage
    this.problems = problems
  }
}

/** A 409 whose code is ``revision_conflict``. Other 409s stay a plain ``GameApiError``. */
export class GameRevisionConflict extends GameApiError {
  constructor(serverMessage = '') {
    super(409, 'revision_conflict', serverMessage)
    this.name = 'GameRevisionConflict'
  }
}

interface Detail { code: string; message: string; problems: GameProblem[] }

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function text(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

/** FastAPI request validation answers a list of ``{loc, msg, type}``. */
function validationProblems(items: unknown[]): GameProblem[] {
  return items.filter(isRecord).map(item => ({
    code: text(item.type) || 'invalid_request',
    message: text(item.msg),
    field: Array.isArray(item.loc) ? item.loc.map(String).join('.') : undefined,
  }))
}

function readDetail(detail: unknown): Detail {
  if (typeof detail === 'string') return { code: '', message: detail, problems: [] }
  if (Array.isArray(detail)) return { code: 'invalid_request', message: '', problems: validationProblems(detail) }
  if (!isRecord(detail)) return { code: '', message: '', problems: [] }
  const problems = Array.isArray(detail.problems) ? detail.problems.filter(isRecord) as GameProblem[] : []
  return { code: text(detail.code), message: text(detail.message), problems }
}

async function gameError(response: Response): Promise<GameApiError> {
  const body = await response.json().catch(() => null) as { detail?: unknown } | null
  const detail = readDetail(body?.detail)
  if (response.status === 409 && detail.code === 'revision_conflict') return new GameRevisionConflict(detail.message)
  const code = detail.code || (response.status === 404 ? 'not_found' : '')
  return new GameApiError(response.status, code, detail.message, detail.problems)
}

async function gameResponse<T>(responsePromise: Promise<Response>): Promise<T> {
  const response = await responsePromise
  if (response.status === 204) return undefined as T
  if (!response.ok) throw await gameError(response)
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
  return gameResponse(send('/api/v1/games/presets', 'GET'))
}

export function fetchGameLibrary(workspace: string): Promise<GameLibrary> {
  return gameResponse(send(`/api/v1/games?workspace=${encodeURIComponent(workspace)}`, 'GET'))
}

export function fetchGame(workspace: string, gameId: string): Promise<Game> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}?workspace=${encodeURIComponent(workspace)}`, 'GET'))
}

export function createGame(workspace: string, game: Record<string, unknown>): Promise<Game> {
  return gameResponse(send('/api/v1/games', 'POST', { workspace, game }))
}

export function updateGame(workspace: string, gameId: string, patch: GamePatch, baseRevision: number): Promise<Game> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}`, 'PUT', {
    workspace, patch, base_revision: baseRevision,
  }))
}

export function deleteGame(workspace: string, gameId: string): Promise<void> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}?workspace=${encodeURIComponent(workspace)}`, 'DELETE'))
}

export function approveGameStyle(workspace: string, gameId: string, baseRevision: number, references: StyleReference[]): Promise<Game> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/style/approve`, 'POST', {
    workspace,
    base_revision: baseRevision,
    references: references.map(item => ({ asset_id: item.assetId, attempt_id: item.attemptId })),
  }))
}

export function updateGameAsset(workspace: string, gameId: string, assetId: string, patch: Record<string, unknown>, baseRevision: number): Promise<unknown> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/assets/${encodeURIComponent(assetId)}`, 'PATCH', {
    workspace, patch, base_revision: baseRevision,
  }))
}

export function approveGameAttempt(workspace: string, gameId: string, assetId: string, attemptId: string, baseRevision: number): Promise<unknown> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/assets/${encodeURIComponent(assetId)}/approve`, 'POST', {
    workspace, attempt_id: attemptId, base_revision: baseRevision,
  }))
}

export function rejectGameAttempt(workspace: string, gameId: string, assetId: string, attemptId: string, note: string, baseRevision: number): Promise<unknown> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/assets/${encodeURIComponent(assetId)}/reject`, 'POST', {
    workspace, attempt_id: attemptId, note, base_revision: baseRevision,
  }))
}

export function lockGameAsset(workspace: string, gameId: string, assetId: string, locked: boolean, baseRevision: number): Promise<unknown> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/assets/${encodeURIComponent(assetId)}/lock`, 'POST', {
    workspace, locked, base_revision: baseRevision,
  }))
}

export function exportGame(workspace: string, gameId: string): Promise<ExportResult> {
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/export`, 'POST', { workspace }))
}

export function gameAssetsFromList(workspace: string, gameId: string, body: { text?: string; csv?: string; items?: unknown[]; format?: string; check?: boolean; replace?: boolean }): Promise<ListReport> {
  const payload: Record<string, unknown> = { workspace, check: Boolean(body.check), replace: Boolean(body.replace) }
  if (body.items) payload.items = body.items
  else if (body.format === 'csv') payload.csv = body.csv || body.text || ''
  else payload.text = body.text || ''
  return gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/assets/from-list`, 'POST', payload))
}

function asJob(job: ProduceJob & { jobId?: string }): ProduceJob {
  return { ...job, id: job.id || job.jobId || '' }
}

export async function produceGame(workspace: string, gameId: string, body: { assetIds?: string[]; kinds?: string[]; rerender?: boolean; candidates?: number } = {}): Promise<ProduceJob> {
  const payload: Record<string, unknown> = { workspace, rerender: Boolean(body.rerender) }
  if (body.assetIds) payload.asset_ids = body.assetIds
  if (body.kinds) payload.kinds = body.kinds
  if (body.candidates) payload.candidates = body.candidates
  return asJob(await gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/produce`, 'POST', payload)))
}

export async function fetchProduceJob(workspace: string, jobId: string): Promise<ProduceJob> {
  return asJob(await gameResponse(send(`/api/v1/games/produce/jobs/${encodeURIComponent(jobId)}?workspace=${encodeURIComponent(workspace)}`, 'GET')))
}

export async function cancelProduceJob(workspace: string, jobId: string): Promise<ProduceJob> {
  return asJob(await gameResponse(send(`/api/v1/games/produce/jobs/${encodeURIComponent(jobId)}/cancel`, 'POST', { workspace })))
}

export async function resumeProduceJob(workspace: string, jobId: string): Promise<ProduceJob> {
  return asJob(await gameResponse(send(`/api/v1/games/produce/jobs/${encodeURIComponent(jobId)}/resume`, 'POST', { workspace })))
}

export async function startStyleSheet(workspace: string, gameId: string): Promise<ProduceJob> {
  return asJob(await gameResponse(send(`/api/v1/games/${encodeURIComponent(gameId)}/style/sheet`, 'POST', { workspace })))
}
