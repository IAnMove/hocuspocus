export type StoryActivityStatus = 'running' | 'completed' | 'failed' | 'cancelled'

export interface StoryActivitySnapshot {
  id: string
  kind: 'story_lab'
  title: string
  status: StoryActivityStatus
  phase: string
  message: string
  current?: number
  total?: number
  error?: string | null
}

interface StoryActivityLifecycleOptions {
  id: string
  title: string
  phase: string
  message: string
  total?: number
  publish: (activity: StoryActivitySnapshot) => void
  scheduleDismiss: (activityId: string) => void
}

/**
 * Own the short-lived client side of a Story Lab operation.
 *
 * A backend job may replace this wrapper as soon as it returns its durable ID.
 * `handoff` makes the wrapper terminal before it can be dismissed, and every
 * later callback becomes a no-op so a late poll cannot reopen the old root.
 */
export function createStoryActivityLifecycle(options: StoryActivityLifecycleOptions) {
  const total = options.total || 0
  let terminal = false

  const publishRunning = (
    message: string,
    phase = options.phase,
    current = 0,
    nextTotal = total,
  ) => {
    if (terminal) return
    options.publish({
      id: options.id,
      kind: 'story_lab',
      title: options.title,
      status: 'running',
      phase,
      message,
      current,
      total: nextTotal,
    })
  }

  const publishDismissibleTerminal = (
    status: 'completed' | 'cancelled',
    phase: string,
    message: string,
  ) => {
    if (terminal) return
    terminal = true
    options.publish({
      id: options.id,
      kind: 'story_lab',
      title: options.title,
      status,
      phase,
      message,
      current: total || 1,
      total: total || 1,
      error: null,
    })
    // The store serializes this dismissal behind the terminal upsert. This is
    // deliberately scheduled only after publishing a terminal snapshot.
    options.scheduleDismiss(options.id)
  }

  publishRunning(options.message)

  return {
    id: options.id,
    update: publishRunning,
    fail: (error: unknown, phase = options.phase) => {
      if (terminal) return
      terminal = true
      const message = error instanceof Error ? error.message : String(error)
      options.publish({
        id: options.id,
        kind: 'story_lab',
        title: options.title,
        status: 'failed',
        phase,
        message,
        error: message,
      })
    },
    cancel: (message = 'Cancelled') => {
      publishDismissibleTerminal('cancelled', 'cancelled', message)
    },
    finish: (message = 'Complete', phase = 'completed') => {
      publishDismissibleTerminal('completed', phase, message)
    },
    handoff: (message: string) => {
      publishDismissibleTerminal('completed', 'handed_off', message)
    },
    isTerminal: () => terminal,
  }
}
