import { BASE, HttpError } from './http'

export type InstallState = 'unsupported' | 'not_installed' | 'installed' | 'needs_update' | 'running'

export interface InstallJob {
  component: string
  kind: 'install' | 'uninstall'
  state: 'running' | 'succeeded' | 'failed'
  startedAt: number
  finishedAt: number | null
  /** Machine-readable reason of a failed job; the UI translates it. */
  code: string | null
  /** English detail from the server, shown only as a fallback. */
  message: string | null
}

export interface InstallComponent {
  id: string
  engine: string
  title: string
  summary: string
  estimatedBytes: number
  restartRequired: boolean
  state: InstallState
  supported: boolean
  reason: string | null
  /** null while the server is still measuring the folder. */
  sizeBytes: number | null
  job: InstallJob | null
}

export interface InstallStatus {
  launcher: { available: boolean; reason: 'not_in_pinokio' | 'no_pterm' | null }
  disk: { freeBytes: number; totalBytes: number }
  base: { title: string; summary: string; estimatedBytes: number; engine: string; installed: boolean; state: InstallState; sizeBytes: number | null }
  components: InstallComponent[]
  /** Id of the component being installed or removed; only one change runs at a time. */
  busy: string | null
}

/** A refusal from the install routes: `code` is stable, `message` is English. */
export class InstallApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(status: number, code: string, message: string) {
    super(message)
    this.name = 'InstallApiError'
    this.status = status
    this.code = code
  }
}

async function readJson<T>(res: Response): Promise<T> {
  if (res.ok) return res.json()
  let code = 'request_failed'
  let message = `Request failed (${res.status})`
  try {
    const body = await res.json()
    if (body?.detail?.code) {
      code = body.detail.code
      message = body.detail.message ?? message
    }
  } catch {
    throw new HttpError(res.status, message)
  }
  throw new InstallApiError(res.status, code, message)
}

const route = (id: string, action: string) => `${BASE}/api/v1/system/install/${encodeURIComponent(id)}/${action}`

export async function fetchInstallStatus(): Promise<InstallStatus> {
  return readJson(await fetch(`${BASE}/api/v1/system/install`))
}

export async function startComponentInstall(id: string): Promise<InstallJob> {
  return readJson(await fetch(route(id, 'install'), { method: 'POST' }))
}

export async function startComponentUninstall(id: string): Promise<InstallJob> {
  return readJson(await fetch(route(id, 'uninstall'), { method: 'POST' }))
}

export async function fetchComponentOutput(id: string, lines = 40): Promise<string[]> {
  const body = await readJson<{ lines: string[] }>(await fetch(`${route(id, 'output')}?lines=${lines}`))
  return body.lines
}
