import type { RenderLevel } from './renderEstimate.ts'

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>

const ROUTES = {
  world3d: {
    operation: 'scenes.world3d.export',
    submit: '/api/v1/scenes/world3d/export',
    receipt: '/api/v1/scenes/world3d/export/receipt',
    cancel: '/api/v1/scenes/world3d/export/cancel',
  },
  video2d: {
    operation: 'scenes.video2d.export',
    submit: '/api/v1/scenes/video2d/export',
    receipt: '/api/v1/scenes/video2d/export/receipt',
    cancel: '/api/v1/scenes/video2d/export/cancel',
  },
} as const

export type ServerRenderKind = keyof typeof ROUTES

export type ServerRenderRequest = {
  kind: ServerRenderKind
  workspace: string
  document: unknown
  level: Exclude<RenderLevel, 'draft'>
  shutter: number
  signal?: AbortSignal
  onProgress?: (index: number, total: number) => void
  fetchImpl?: FetchLike
  sleep?: (ms: number) => Promise<void>
}

type TaskView = { status?: string; message?: string; current?: number; total?: number }
type ReceiptView = { artifacts?: { name?: string; url?: string }[] }

function sleep(ms: number) {
  return new Promise<void>(resolve => { setTimeout(resolve, ms) })
}

function intentId(): string {
  const stamp = Date.now().toString(36)
  const salt = Math.random().toString(36).slice(2, 10)
  return `render-${stamp}-${salt}`
}

async function failureMessage(response: Response): Promise<string> {
  try {
    const body = await response.json() as { message?: string; detail?: { message?: string } }
    if (typeof body.detail?.message === 'string') return body.detail.message
    if (typeof body.message === 'string') return body.message
  } catch { /* The status line is enough when the body is not JSON. */ }
  return `Export failed (${response.status})`
}

function artifactOf(receipt: ReceiptView | undefined): { name: string; url: string } | null {
  const item = receipt?.artifacts?.[0]
  if (!item || typeof item.name !== 'string' || typeof item.url !== 'string') return null
  return { name: item.name, url: item.url }
}

async function readReceipt(fetchImpl: FetchLike, kind: ServerRenderKind, workspace: string, id: string, signal: AbortSignal | undefined) {
  const route = ROUTES[kind]
  const query = `workspace=${encodeURIComponent(workspace)}&intent_id=${encodeURIComponent(id)}`
  const response = await fetchImpl(`${route.receipt}?${query}`, { signal })
  if (!response.ok) throw new Error(await failureMessage(response))
  return await response.json() as { task?: TaskView; receipt?: ReceiptView }
}

export async function renderOnServer(request: ServerRenderRequest): Promise<{ name: string; url: string }> {
  const fetchImpl = request.fetchImpl ?? fetch
  const pause = request.sleep ?? sleep
  const route = ROUTES[request.kind]
  const id = intentId()
  const signal = request.signal
  const cancel = () => {
    void fetchImpl(route.cancel, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workspace: request.workspace, intent_id: id }),
    }).catch(() => undefined)
  }
  signal?.addEventListener('abort', cancel, { once: true })
  try {
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    const submitted = await fetchImpl(route.submit, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        version: 1,
        operation: route.operation,
        intent_id: id,
        input: {
          workspace: request.workspace,
          document: request.document,
          quality: request.level,
          shutter: request.shutter,
        },
      }),
      signal,
    })
    if (!submitted.ok) throw new Error(await failureMessage(submitted))
    for (;;) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
      const viewed = await readReceipt(fetchImpl, request.kind, request.workspace, id, signal)
      const task = viewed.task
      if (typeof task?.current === 'number' && typeof task.total === 'number') request.onProgress?.(task.current, task.total)
      if (task?.status === 'completed') {
        const saved = artifactOf(viewed.receipt)
        if (!saved) throw new Error('The server finished without a video file.')
        return saved
      }
      if (task?.status === 'failed' || task?.status === 'cancelled' || task?.status === 'interrupted') {
        throw new Error(task.message || 'The server render did not finish.')
      }
      await pause(2000)
    }
  } finally {
    signal?.removeEventListener('abort', cancel)
  }
}
