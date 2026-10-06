import { useEffect, useState } from 'react'
import * as api from '../../api/client'
import type { CanonicalTask } from '../../api/client'

/**
 * Work an MCP agent or the Wizard asked for, read with ``origin=agent`` so a long
 * agent session is not crowded out of the 300 most recent tasks. Refetched when
 * the live task feed changes (``refreshKey``) while the "Agents" view is shown.
 */
export function useAgentActivityTasks(workspace: string, enabled: boolean, refreshKey: string) {
  // Keyed by workspace so a switch never shows the previous workspace's agent work.
  const [state, setState] = useState<{ workspace: string; tasks: CanonicalTask[]; failed: boolean }>({ workspace, tasks: [], failed: false })
  useEffect(() => {
    if (!enabled) return
    let mounted = true
    api.fetchCanonicalTasks(workspace, 'all', { origin: 'agent' })
      .then(result => { if (mounted) setState({ workspace, tasks: result.tasks, failed: false }) })
      .catch(() => { if (mounted) setState(current => ({ workspace, tasks: current.workspace === workspace ? current.tasks : [], failed: true })) })
    return () => { mounted = false }
  }, [enabled, workspace, refreshKey])
  const current = enabled && state.workspace === workspace
  return { tasks: current ? state.tasks : [], failed: current && state.failed }
}

/** One list from two snapshots of the same registry; the newer copy of a task wins. */
export function mergeTaskSnapshots(primary: CanonicalTask[], extra: CanonicalTask[]): CanonicalTask[] {
  const byId = new Map(primary.map(task => [task.id, task]))
  for (const task of extra) {
    const current = byId.get(task.id)
    if (!current || Number(task.updated_at) > Number(current.updated_at)) byId.set(task.id, task)
  }
  return [...byId.values()]
}

/** A cheap change marker for the live feed: refetch the agent view when any task changes. */
export function taskFeedKey(tasks: CanonicalTask[]): string {
  let latest = 0
  for (const task of tasks) latest = Math.max(latest, Number(task.updated_at) || 0)
  return `${tasks.length}:${latest}`
}
