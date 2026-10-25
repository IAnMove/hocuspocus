import { downloadModel } from '../../api/generation'

/** The one operation the clip button, the Wizard and MCP all call. */
export const LIPSYNC_REDO = 'shot.lipsync.redo'

export const LIPSYNC_ENGINES = ['infinitetalk', 'longcat_avatar'] as const

export type LipsyncEngine = typeof LIPSYNC_ENGINES[number]

export type LipsyncRedoInput = {
  workspace: string
  engine: LipsyncEngine
  production_id?: string
  series_id?: string
  episode_id?: string
  shot?: string
  clip?: string
  source?: string
  audio?: string
  span?: [number, number]
  offset?: number
  confirm_download?: boolean
}

const FIELDS = [
  'series_id', 'episode_id', 'shot', 'production_id', 'clip', 'source', 'audio', 'span', 'offset', 'confirm_download',
] as const

export type LipsyncKind = 'done' | 'download' | 'downloading' | 'error'

export type LipsyncRead = {
  kind: LipsyncKind
  file?: string
  verdict?: string
  bytes?: number
  modelType?: string
  message?: string
}

type Note = (key: string, options?: Record<string, unknown>) => string

export function lipsyncRedoEnvelope(input: LipsyncRedoInput, intentId?: string) {
  return { operation: LIPSYNC_REDO, version: 1 as const, ...(intentId ? { intent_id: intentId } : {}), input }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function sized(body: Record<string, unknown>, kind: 'download' | 'downloading'): LipsyncRead {
  return {
    kind,
    bytes: typeof body.bytes === 'number' ? body.bytes : 0,
    modelType: typeof body.model_type === 'string' ? body.model_type : '',
    message: typeof body.message === 'string' ? body.message : '',
  }
}

/** 409 with a disk size asks for the existing download. A finished call names the new take and the verdict. */
export function interpretLipsyncReply(status: number, reply: unknown): LipsyncRead {
  const body = record(reply)
  const detail = record(body.detail)
  const result = record(body.result)
  if (status === 409 && detail.code === 'model_unavailable') return sized(detail, 'download')
  if (status >= 200 && status < 300 && result.status === 'downloading') return sized(result, 'downloading')
  if (status >= 200 && status < 300 && typeof result.file === 'string') {
    return { kind: 'done', file: result.file, verdict: typeof result.verdict === 'string' ? result.verdict : '' }
  }
  const message = typeof detail.message === 'string' ? detail.message : typeof body.detail === 'string' ? body.detail : ''
  return { kind: 'error', message }
}

export function lipsyncNote(read: LipsyncRead, t: Note): string {
  if (read.kind === 'done') return t('replies.lipsRedone', { verdict: read.verdict ?? '', file: read.file ?? '' })
  if (read.kind === 'downloading') return t('replies.lipsDownloadStarted', { model: read.modelType ?? '', bytes: read.bytes ?? 0 })
  if (read.kind === 'download') return t('replies.lipsNeedDownload', { model: read.modelType ?? '', bytes: read.bytes ?? 0 })
  return read.message || t('replies.lipsFailed')
}

/** Copy only the keys the operation accepts, and keep the caller's engine. */
export function lipsyncInput(raw: Record<string, unknown>, workspace: string, engine: LipsyncEngine): LipsyncRedoInput {
  const input: Record<string, unknown> = { workspace, engine }
  for (const key of FIELDS) {
    if (raw[key] !== undefined) input[key] = raw[key]
  }
  return input as LipsyncRedoInput
}

export async function postLipsyncRedo(
  input: LipsyncRedoInput,
  options?: { surface?: string, intentId?: string, fetchImpl?: typeof fetch },
) {
  const fetchImpl = options?.fetchImpl ?? fetch
  const response = await fetchImpl('/api/v1/media/commands', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'X-Hocus-UI-Surface': options?.surface || 'ui' },
    body: JSON.stringify(lipsyncRedoEnvelope(input, options?.intentId)),
  })
  return { status: response.status, body: await response.json().catch(() => ({})) }
}

export async function runLipsyncRedo(input: LipsyncRedoInput, t: Note) {
  const posted = await postLipsyncRedo(input)
  const read = interpretLipsyncReply(posted.status, posted.body)
  const pending = read.kind === 'download' && read.modelType ? { model: read.modelType, bytes: read.bytes || 0 } : null
  return { note: lipsyncNote(read, t), pending, read }
}

/** The Install-tab download. The size was already shown; this call does not wait for the files. */
export async function confirmLipsyncDownload(model: string): Promise<void> {
  await downloadModel(model)
}
