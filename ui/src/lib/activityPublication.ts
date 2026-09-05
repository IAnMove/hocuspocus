const TERMINAL_ACTIVITY_STATUSES = new Set(['completed', 'failed', 'cancelled'])

type TimerHandle = ReturnType<typeof setTimeout>

interface PublicationState<T> {
  lastHash: string
  lastPublishedAt: number
  pending: T | null
  pendingHash: string
  timer: TimerHandle | null
  emit: ((value: T) => void) | null
}

export interface ActivityPublicationGate<T extends { id: string; status: string }> {
  publish: (value: T, emit: (value: T) => void) => void
  clear: (id: string) => void
}

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => key !== 'updatedAt')
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, stableValue(item)]),
  )
}

export function activityPublicationHash(value: unknown): string {
  return JSON.stringify(stableValue(value))
}

export function createActivityPublicationGate<T extends { id: string; status: string }>(
  intervalMs = 1500,
  now: () => number = Date.now,
  schedule: (callback: () => void, delayMs: number) => TimerHandle = setTimeout,
  cancel: (timer: TimerHandle) => void = clearTimeout,
): ActivityPublicationGate<T> {
  const states = new Map<string, PublicationState<T>>()

  const clearPending = (state: PublicationState<T>) => {
    if (state.timer !== null) cancel(state.timer)
    state.pending = null
    state.pendingHash = ''
    state.timer = null
  }

  const emitNow = (state: PublicationState<T>, value: T, hash: string) => {
    clearPending(state)
    state.lastHash = hash
    state.lastPublishedAt = now()
    state.emit?.(value)
  }

  return {
    publish(value, emit) {
      const hash = activityPublicationHash(value)
      const state = states.get(value.id) || {
        lastHash: '', lastPublishedAt: 0, pending: null, pendingHash: '', timer: null, emit: null,
      }
      state.emit = emit
      states.set(value.id, state)

      if (hash === state.lastHash) {
        // The newest poll returned to the already-published state. A different
        // throttled intermediate state must not leak out later.
        clearPending(state)
        return
      }
      if (hash === state.pendingHash) return

      const terminal = TERMINAL_ACTIVITY_STATUSES.has(value.status)
      const elapsed = now() - state.lastPublishedAt
      if (terminal || !state.lastHash || elapsed >= intervalMs) {
        emitNow(state, value, hash)
        return
      }

      state.pending = value
      state.pendingHash = hash
      if (state.timer !== null) return
      state.timer = schedule(() => {
        state.timer = null
        const pending = state.pending
        const pendingHash = state.pendingHash
        state.pending = null
        state.pendingHash = ''
        if (pending && pendingHash !== state.lastHash) emitNow(state, pending, pendingHash)
      }, Math.max(0, intervalMs - elapsed))
    },
    clear(id) {
      const state = states.get(id)
      if (state) clearPending(state)
      states.delete(id)
    },
  }
}
