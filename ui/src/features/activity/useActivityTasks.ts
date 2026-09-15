import { useEffect, useRef, useState } from 'react'
import * as api from '../../api/client'
import type { CanonicalTask } from '../../api/client'
import { applyCanonicalTaskEvent, reconcileCanonicalTaskSnapshot } from '../../lib/canonicalTaskEvents'
import { publishCanonicalTasks } from './canonicalTaskFeed'
import type { TaskControlAction, TaskControlFailure } from './executionDetail'
import { isLiveStatus } from './lineage'

const CONNECTED_RECONCILE_MS = 60_000
const DISCONNECTED_POLL_MS = 5_000

function controlRequest(taskId: string, workspace: string, action: TaskControlAction) {
  if (action === 'cancel') return api.cancelCanonicalTask(taskId, workspace)
  if (action === 'resume') return api.resumeCanonicalTask(taskId, workspace)
  return api.dismissCanonicalTask(taskId, workspace)
}

function applyControlSuccess(
  current: CanonicalTask[],
  taskId: string,
  action: TaskControlAction,
  result: CanonicalTask,
): CanonicalTask[] {
  if (action === 'dismiss') return current.filter(item => item.id !== taskId)
  return current.map(item => {
    if (item.id !== taskId) return item
    if (Number(result.updated_at) < Number(item.updated_at)) return item
    return result
  })
}

export function useActivityTasks(activeWorkspace: string) {
  const workspaceRef = useRef(activeWorkspace)
  workspaceRef.current = activeWorkspace
  const [tasks, setTasks] = useState<CanonicalTask[]>([])
  const tasksRef = useRef<CanonicalTask[]>([])
  const [busyIds, setBusyIds] = useState<Set<string>>(() => new Set())
  const [controlFailures, setControlFailures] = useState<Record<string, TaskControlFailure>>({})

  const commitTasks = (next: CanonicalTask[]) => {
    tasksRef.current = next
    setTasks(next)
    publishCanonicalTasks(next)
  }

  useEffect(() => {
    let mounted = true
    let refreshPending = false
    let streamConnected = false
    let pollTimer: number | null = null
    let closeEvents: () => void = () => undefined
    let unknownTaskBaseline = 0

    const refresh = async (): Promise<number | null> => {
      if (refreshPending) return null
      refreshPending = true
      try {
        const result = await api.fetchCanonicalTasks(activeWorkspace, 'all')
        if (mounted) {
          unknownTaskBaseline = Math.max(
            unknownTaskBaseline,
            ...result.tasks.map(task => Number(task.updated_at || 0)),
          )
          commitTasks(reconcileCanonicalTaskSnapshot(tasksRef.current, result.tasks, unknownTaskBaseline))
        }
        return Number(result.latest_event_id || 0)
      } catch {
        return null
      } finally {
        refreshPending = false
      }
    }

    const schedulePoll = () => {
      if (!mounted) return
      if (pollTimer !== null) window.clearTimeout(pollTimer)
      pollTimer = window.setTimeout(async () => {
        pollTimer = null
        await refresh()
        schedulePoll()
      }, streamConnected ? CONNECTED_RECONCILE_MS : DISCONNECTED_POLL_MS)
    }

    const connectAfterSnapshot = async () => {
      const initialEventId = await refresh()
      if (!mounted) return
      // Never replay from zero after a failed snapshot. Retrying the small
      // snapshot request first is bounded; opening SSE without its cursor is
      // not bounded on a long-lived workspace.
      if (initialEventId === null) {
        pollTimer = window.setTimeout(() => {
          pollTimer = null
          void connectAfterSnapshot()
        }, DISCONNECTED_POLL_MS)
        return
      }
      closeEvents = api.subscribeCanonicalTaskEvents(
        activeWorkspace,
        event => {
          const result = applyCanonicalTaskEvent(tasksRef.current, event, unknownTaskBaseline)
          if (result.tasks !== tasksRef.current) commitTasks(result.tasks)
          if (result.needsRefresh) void refresh()
        },
        () => undefined,
        state => {
          if (!mounted) return
          streamConnected = state === 'open'
          schedulePoll()
        },
        initialEventId,
      )
      schedulePoll()
    }

    tasksRef.current = []
    setTasks([])
    publishCanonicalTasks([])
    setControlFailures({})
    void connectAfterSnapshot()
    return () => {
      mounted = false
      closeEvents()
      if (pollTimer !== null) window.clearTimeout(pollTimer)
    }
  }, [activeWorkspace])

  const runControl = (task: CanonicalTask, action: TaskControlAction, onFailure?: () => void) => {
    if (busyIds.has(task.id)) return
    const workspace = activeWorkspace
    const taskId = task.id
    setBusyIds(current => new Set(current).add(taskId))
    void controlRequest(taskId, workspace, action).then(result => {
      if (workspaceRef.current !== workspace) return
      commitTasks(applyControlSuccess(tasksRef.current, taskId, action, result as CanonicalTask))
      setControlFailures(current => {
        if (!current[taskId]) return current
        const nextFailures = { ...current }
        delete nextFailures[taskId]
        return nextFailures
      })
    }).catch(reason => {
      if (workspaceRef.current !== workspace) return
      const message = reason instanceof Error ? reason.message : String(reason)
      setControlFailures(current => ({ ...current, [taskId]: { action, message } }))
      onFailure?.()
    }).finally(() => {
      setBusyIds(current => {
        const next = new Set(current)
        next.delete(taskId)
        return next
      })
    })
  }

  return { tasks, tasksRef, busyIds, controlFailures, runControl }
}

export function hideTerminalHistory(tasks: CanonicalTask[], hidden: Set<string>): Set<string> {
  const next = new Set(hidden)
  for (const task of tasks) {
    if (!isLiveStatus(task.status)) next.add(task.id)
  }
  return next
}
