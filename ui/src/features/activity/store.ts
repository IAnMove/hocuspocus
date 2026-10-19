import * as api from '../../api/client'
import { createActivityPublicationGate } from '../../lib/activityPublication'
import { createKeyedWriteSequencer } from '../../lib/keyedWriteSequencer'
import type { GenerationDetails } from '../../types'
import type { SliceCreator } from '../../stores/storeApi'

export interface ForegroundActivity {
  id: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
  phase: string
  message: string
  title?: string
  kind?: string
  parentId?: string
  current?: number
  total?: number
  progress?: number
  detailMessage?: string
  detailVolatile?: boolean
  detailCurrent?: number
  detailTotal?: number
  tokenUsage?: {
    promptTokens?: number
    completionTokens?: number
    totalTokens?: number
    calls?: number
  }
  generationDetails?: GenerationDetails
  error?: string | null
  startedAt?: number
  updatedAt?: number
}

export type ActivitySlice = {
  foregroundActivity: ForegroundActivity | null
  activities: Record<string, ForegroundActivity>
  upsertActivity: (activity: ForegroundActivity) => void
  removeActivity: (activityId: string) => void
  setForegroundActivity: (activity: ForegroundActivity | null) => void
}

export type ActivitySliceHost = ActivitySlice & {
  activeWorkspace: string
}

const CLIENT_ACTIVITY_TERMINAL_STATUSES = new Set<ForegroundActivity['status']>([
  'completed',
  'failed',
  'cancelled',
])
const _canonicalClientTaskWrites = createKeyedWriteSequencer()
const _activityPublicationGate = createActivityPublicationGate<ForegroundActivity>()

export function beginAppActivity(
  get: () => ActivitySlice,
  options: {
    kind: string
    title: string
    phase: string
    message: string
    total?: number
    generationDetails?: GenerationDetails
  },
) {
  const id = `${options.kind}:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`
  const report = (
    phase: string,
    message: string,
    current = 0,
    total = options.total || 0,
    details?: Partial<Pick<ForegroundActivity, 'detailMessage' | 'detailVolatile' | 'detailCurrent' | 'detailTotal' | 'tokenUsage' | 'generationDetails'>>,
  ) => get().upsertActivity({
    id,
    kind: options.kind,
    title: options.title,
    status: 'running',
    phase,
    message,
    current,
    total,
    ...details,
  })
  report(options.phase, options.message, 0, options.total || 0, {
    generationDetails: options.generationDetails,
  })
  return {
    id,
    report,
    finish: (message = 'Complete') => {
      const clearVolatileDetail = get().activities[id]?.detailVolatile
        ? { detailMessage: '', detailVolatile: false }
        : {}
      get().upsertActivity({
        id,
        kind: options.kind,
        title: options.title,
        status: 'completed',
        phase: 'completed',
        message,
        current: options.total || 1,
        total: options.total || 1,
        ...clearVolatileDetail,
      })
      window.setTimeout(() => get().removeActivity(id), 4000)
    },
    fail: (error: unknown, phase = options.phase) => {
      const message = error instanceof Error ? error.message : String(error)
      const clearVolatileDetail = get().activities[id]?.detailVolatile
        ? { detailMessage: '', detailVolatile: false }
        : {}
      get().upsertActivity({
        id,
        kind: options.kind,
        title: options.title,
        status: 'failed',
        phase,
        message,
        error: message,
        ...clearVolatileDetail,
      })
    },
  }
}

export const createActivitySlice: SliceCreator<ActivitySlice, ActivitySliceHost> = (set, get) => ({
  foregroundActivity: null,
  activities: {},
  upsertActivity: (activity) => {
    const previous = get().activities[activity.id]
    if (
      previous
      && CLIENT_ACTIVITY_TERMINAL_STATUSES.has(previous.status)
      && !CLIENT_ACTIVITY_TERMINAL_STATUSES.has(activity.status)
    ) return
    const now = Date.now()
    const published = {
      ...previous,
      ...activity,
      workspace: get().activeWorkspace,
      startedAt: previous?.startedAt || activity.startedAt || now,
      updatedAt: activity.updatedAt || now,
    }
    // Keep each client root's running -> terminal -> dismissal writes ordered.
    // Different activities still publish concurrently, and observability never
    // blocks the foreground operation.
    _activityPublicationGate.publish(published, latest => {
      void _canonicalClientTaskWrites.enqueue(activity.id, async () => {
        await api.upsertCanonicalClientTask(latest as unknown as Record<string, unknown>)
      }).catch(() => undefined)
    })
    set(state => ({
      activities: { ...state.activities, [activity.id]: published },
    }))
  },
  removeActivity: (activityId) => {
    const activity = get().activities[activityId]
    if (!activity || !CLIENT_ACTIVITY_TERMINAL_STATUSES.has(activity.status)) return
    const workspace = get().activeWorkspace
    void _canonicalClientTaskWrites.enqueue(activityId, async () => {
      await api.dismissCanonicalTask(api.canonicalClientTaskId(activityId), workspace)
    }).catch(() => undefined)
    _activityPublicationGate.clear(activityId)
    set(state => {
      if (!state.activities[activityId]) return {}
      const activities = { ...state.activities }
      delete activities[activityId]
      return { activities }
    })
  },
  // Compatibility bridge for older feature panels. New workflows should use
  // the registry directly so concurrent activities cannot overwrite one another.
  setForegroundActivity: (activity) => set(state => {
    const activities = { ...state.activities }
    if (!activity) {
      if (state.foregroundActivity?.id) delete activities[state.foregroundActivity.id]
      return { foregroundActivity: null, activities }
    }
    if (state.foregroundActivity?.id && state.foregroundActivity.id !== activity.id) {
      delete activities[state.foregroundActivity.id]
    }
    const previous = activities[activity.id]
    const now = Date.now()
    const normalized = {
      ...previous,
      ...activity,
      startedAt: previous?.startedAt || activity.startedAt || now,
      updatedAt: activity.updatedAt || now,
    }
    activities[activity.id] = normalized
    return { foregroundActivity: normalized, activities }
  }),
})
