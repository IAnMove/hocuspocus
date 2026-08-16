export interface CanonicalTaskLike {
  id: string
  status: string
  updated_at: number
  resumable: boolean
}

export interface CanonicalTaskEvent {
  event_id: number
  task_id: string
  root_id: string
  sequence: number
  timestamp: number
  type: string
  changes: Record<string, unknown>
  context?: Record<string, unknown>
}

export type CanonicalTaskStreamState = 'connecting' | 'open' | 'retrying' | 'closed'

export interface ApplyCanonicalTaskEventResult<T> {
  tasks: T[]
  needsRefresh: boolean
}

interface TaskEventSource {
  onopen: ((event: Event) => void) | null
  onerror: ((event: Event) => void) | null
  addEventListener(type: string, listener: (event: Event) => void): void
  close(): void
}

type RetryHandle = number

interface TaskEventStreamOptions {
  eventSourceFactory?: (url: string) => TaskEventSource
  scheduleRetry?: (callback: () => void, delayMs: number) => RetryHandle
  cancelRetry?: (handle: RetryHandle) => void
  initialRetryMs?: number
  maximumRetryMs?: number
  initialEventId?: number
}

const RESUMABLE_STATUSES = new Set(['failed', 'cancelled', 'interrupted'])
const REMOVAL_EVENT_SUFFIXES = ['.deleted', '.dismissed', '.removed']
const ACTIVE_STATUSES = new Set(['created', 'queued', 'waiting_resource', 'running'])

function positiveInteger(value: unknown): number {
  const parsed = Number.parseInt(String(value || ''), 10)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function isCanonicalTaskEvent(value: unknown): value is CanonicalTaskEvent {
  return isRecord(value)
    && typeof value.task_id === 'string'
    && typeof value.type === 'string'
    && isRecord(value.changes)
}

function isRemovalEvent(type: string): boolean {
  return REMOVAL_EVENT_SUFFIXES.some(suffix => type.endsWith(suffix))
}

function isFullCreatedSnapshot(event: CanonicalTaskEvent): boolean {
  return event.type === 'task.created'
    && event.changes.id === event.task_id
    && typeof event.changes.status === 'string'
    && Number.isFinite(Number(event.changes.updated_at))
}

/**
 * Apply a durable task event without re-fetching the whole registry.
 *
 * The first SSE connection replays historical events from cursor zero. A
 * fetched snapshot is newer than those events, so timestamp comparison keeps
 * that replay from temporarily rolling the footer back to an old phase.
 */
export function applyCanonicalTaskEvent<T extends CanonicalTaskLike>(
  tasks: T[],
  event: CanonicalTaskEvent,
  unknownTaskBaseline = 0,
): ApplyCanonicalTaskEventResult<T> {
  if (isRemovalEvent(event.type)) {
    const next = tasks.filter(task => task.id !== event.task_id)
    return { tasks: next.length === tasks.length ? tasks : next, needsRefresh: false }
  }

  const index = tasks.findIndex(task => task.id === event.task_id)
  if (index >= 0) {
    const existing = tasks[index]
    if (Number(event.timestamp || 0) < Number(existing.updated_at || 0)) {
      return { tasks, needsRefresh: false }
    }
    const next = [...tasks]
    next[index] = { ...existing, ...event.changes } as T
    return { tasks: next, needsRefresh: false }
  }

  // The initial SSE history can contain tasks older than the API's 300-task
  // snapshot. Ignore those instead of growing the footer forever or causing a
  // refetch for every historical patch.
  if (unknownTaskBaseline > 0 && Number(event.timestamp || 0) <= unknownTaskBaseline) {
    return { tasks, needsRefresh: false }
  }

  if (isFullCreatedSnapshot(event)) {
    return { tasks: [...tasks, event.changes as unknown as T], needsRefresh: false }
  }

  // A recent partial event for an unknown task means a create event was
  // missed. One coalesced snapshot request is the safest recovery path.
  return { tasks, needsRefresh: true }
}

export function canResumeCanonicalTask(task: Pick<CanonicalTaskLike, 'status' | 'resumable'>): boolean {
  return task.resumable && RESUMABLE_STATUSES.has(task.status)
}

export function canonicalTaskVisualState(status: string): 'active' | 'error' | 'cancelled' | 'completed' | 'neutral' {
  if (ACTIVE_STATUSES.has(status)) return 'active'
  if (status === 'failed' || status === 'interrupted') return 'error'
  if (status === 'cancelled') return 'cancelled'
  if (status === 'completed') return 'completed'
  return 'neutral'
}

/** Keep an SSE update that landed while a full snapshot request was in flight. */
export function reconcileCanonicalTaskSnapshot<T extends CanonicalTaskLike>(
  current: T[],
  snapshot: T[],
  snapshotBoundary: number,
): T[] {
  const currentById = new Map(current.map(task => [task.id, task]))
  const snapshotIds = new Set(snapshot.map(task => task.id))
  const next = snapshot.map(task => {
    const existing = currentById.get(task.id)
    return existing && Number(existing.updated_at || 0) > Number(task.updated_at || 0)
      ? existing
      : task
  })
  for (const task of current) {
    if (!snapshotIds.has(task.id) && Number(task.updated_at || 0) > snapshotBoundary) next.push(task)
  }
  return next
}

export function canonicalTaskEventUrl(baseUrl: string, workspace: string, after = 0): string {
  const query = new URLSearchParams({ workspace })
  if (after > 0) query.set('after', String(after))
  return `${baseUrl}/api/v1/tasks/events?${query}`
}

/**
 * Open a task SSE connection with an explicit replay cursor. EventSource does
 * send Last-Event-ID on its own reconnects, but Maestro's endpoint exposes the
 * same cursor as `after`; rebuilding the connection with that value avoids a
 * replay-from-zero loop and gives us bounded exponential backoff.
 */
export function openCanonicalTaskEventStream(
  baseUrl: string,
  workspace: string,
  onEvent: (event: CanonicalTaskEvent) => void,
  onError?: () => void,
  onStateChange?: (state: CanonicalTaskStreamState) => void,
  options: TaskEventStreamOptions = {},
): () => void {
  const eventSourceFactory = options.eventSourceFactory
    || ((url: string) => new EventSource(url) as unknown as TaskEventSource)
  const scheduleRetry = options.scheduleRetry
    || ((callback: () => void, delayMs: number) => window.setTimeout(callback, delayMs))
  const cancelRetry = options.cancelRetry
    || ((handle: number) => window.clearTimeout(handle))
  const initialRetryMs = Math.max(250, options.initialRetryMs ?? 1000)
  const maximumRetryMs = Math.max(initialRetryMs, options.maximumRetryMs ?? 15_000)

  let source: TaskEventSource | null = null
  let reconnectTimer: RetryHandle | null = null
  let retryMs = initialRetryMs
  let lastEventId = positiveInteger(options.initialEventId)
  let closed = false

  const connect = () => {
    if (closed) return
    onStateChange?.('connecting')
    let current: TaskEventSource
    try {
      current = eventSourceFactory(canonicalTaskEventUrl(baseUrl, workspace, lastEventId))
    } catch {
      onError?.()
      onStateChange?.('retrying')
      reconnectTimer = scheduleRetry(() => {
        reconnectTimer = null
        connect()
      }, retryMs)
      retryMs = Math.min(maximumRetryMs, retryMs * 2)
      return
    }
    source = current

    current.onopen = () => {
      if (closed || source !== current) return
      retryMs = initialRetryMs
      onStateChange?.('open')
    }
    current.addEventListener('task', rawEvent => {
      if (closed || source !== current) return
      const message = rawEvent as MessageEvent<string>
      let parsed: unknown
      try {
        parsed = JSON.parse(message.data)
      } catch {
        const messageId = positiveInteger(message.lastEventId)
        if (messageId > lastEventId) lastEventId = messageId
        return
      }
      if (!isCanonicalTaskEvent(parsed)) {
        const messageId = positiveInteger(message.lastEventId)
        if (messageId > lastEventId) lastEventId = messageId
        return
      }
      const payload = parsed
      const eventId = Math.max(
        positiveInteger(message.lastEventId),
        positiveInteger(payload.event_id),
      )
      if (eventId > 0 && eventId <= lastEventId) return
      if (eventId > 0) lastEventId = eventId
      onEvent(payload)
    })
    current.onerror = () => {
      if (closed || source !== current) return
      current.close()
      source = null
      onError?.()
      onStateChange?.('retrying')
      if (reconnectTimer === null) {
        reconnectTimer = scheduleRetry(() => {
          reconnectTimer = null
          connect()
        }, retryMs)
        retryMs = Math.min(maximumRetryMs, retryMs * 2)
      }
    }
  }

  connect()
  return () => {
    if (closed) return
    closed = true
    source?.close()
    source = null
    if (reconnectTimer !== null) cancelRetry(reconnectTimer)
    reconnectTimer = null
    onStateChange?.('closed')
  }
}
