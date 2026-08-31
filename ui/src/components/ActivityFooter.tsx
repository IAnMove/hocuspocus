import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, CircleSlash2, Eraser, ListVideo, Loader2 } from 'lucide-react'
import * as api from '../api/client'
import type { CanonicalTask } from '../api/client'
import { applyCanonicalTaskEvent, canResumeCanonicalTask, canonicalTaskVisualState, reconcileCanonicalTaskSnapshot } from '../lib/canonicalTaskEvents'
import { formatAppAction, formatAppTimestamp } from '../lib/locale'
import { useStore } from '../stores/useStore'
import { AgentAvatar } from '../features/agent/AgentAvatar'
import { listenForAgentActivityDetails } from '../features/agent/agentUiBus'

const AgentAssistantPanel = lazy(() =>
  import('../features/agent/AgentAssistantPanel').then(module => ({ default: module.AgentAssistantPanel })),
)

const ACTIVE = new Set(['created', 'queued', 'waiting_resource', 'running'])
const CONNECTED_RECONCILE_MS = 60_000
const DISCONNECTED_POLL_MS = 5_000
const HIDDEN_HISTORY_STORAGE_PREFIX = 'maestro-activity-hidden-v1:'
type TaskControlAction = 'cancel' | 'resume' | 'dismiss'
interface TaskControlFailure {
  action: TaskControlAction
  message: string
}
const PHASE_LABELS: Record<string, string> = {
  planning: 'Planning',
  known_series_research: 'Building series bible',
  canon: 'Preparing series canon',
  outline: 'Writing outline',
  script: 'Writing script',
  shots: 'Planning shots',
  canon_validation: 'Validating canon',
  canon_delta: 'Preparing canon changes',
  rendering: 'Rendering',
  generating_images: 'Generating images',
  generating_video: 'Generating video',
  post_processing: 'Post-processing',
  waiting_resource: 'Waiting for resource',
  cancelling: 'Cancelling at a safe boundary',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  interrupted: 'Interrupted',
}

function epochMs(value?: number | null): number | undefined {
  if (!value || !Number.isFinite(value)) return undefined
  return value < 1_000_000_000_000 ? value * 1000 : value
}

function activityMoment(task: CanonicalTask): number {
  if (ACTIVE.has(task.status)) return Number(task.updated_at || task.started_at || task.created_at || 0)
  return Number(task.completed_at || task.started_at || task.created_at || 0)
}

function elapsed(task: CanonicalTask, now: number): string {
  const start = epochMs(task.started_at || task.queued_at || task.created_at)
  if (!start) return ''
  const end = ACTIVE.has(task.status)
    ? now
    : epochMs(task.completed_at || task.updated_at) || now
  const seconds = Math.max(0, Math.floor((end - start) / 1000))
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60
  return hours
    ? `${hours}:${minutes.toString().padStart(2, '0')}:${remainder.toString().padStart(2, '0')}`
    : `${minutes}:${remainder.toString().padStart(2, '0')}`
}

function elapsedSeconds(task: CanonicalTask, now: number): number | undefined {
  const start = epochMs(task.started_at || task.queued_at || task.created_at)
  if (!start) return undefined
  const end = ACTIVE.has(task.status)
    ? now
    : epochMs(task.completed_at || task.updated_at) || now
  return Math.max(0, (end - start) / 1000)
}

function percent(task: CanonicalTask): number {
  if (task.total > 0) return Math.max(0, Math.min(100, (task.current / task.total) * 100))
  return Math.max(0, Math.min(100, Number(task.progress || 0) * 100))
}

function estimatedRemainingSeconds(task: CanonicalTask, now: number): number | undefined {
  if (!ACTIVE.has(task.status)) return undefined
  const elapsed = elapsedSeconds(task, now)
  const fraction = percent(task) / 100
  if (!elapsed || elapsed < 3 || fraction < 0.01 || fraction >= 1) return undefined
  return Math.max(1, Math.round(elapsed * ((1 - fraction) / fraction)))
}

function formatEta(seconds: number | undefined): string {
  if (seconds === undefined) return ''
  const rounded = Math.max(1, Math.round(seconds))
  const hours = Math.floor(rounded / 3600)
  const minutes = Math.floor((rounded % 3600) / 60)
  const remainder = rounded % 60
  if (hours) return `~${hours}h ${minutes.toString().padStart(2, '0')}m`
  if (minutes) return `~${minutes}m ${remainder.toString().padStart(2, '0')}s`
  return `~${remainder}s`
}

function phaseLabel(task: CanonicalTask): string {
  return PHASE_LABELS[task.phase] || task.phase?.replaceAll('_', ' ') || task.status
}

function resources(task: CanonicalTask): string {
  const acquired = task.acquired_resources || []
  const required = task.resource_requirements || []
  if (acquired.length) return `Using ${acquired.join(' · ')}`
  if (task.status === 'waiting_resource' && required.length) return `Waiting for ${required.join(' · ')}`
  return required.length ? `Resources ${required.join(' · ')}` : ''
}

function hiddenHistoryStorageKey(workspace: string): string {
  return `${HIDDEN_HISTORY_STORAGE_PREFIX}${workspace}`
}

function readHiddenHistory(workspace: string): Set<string> {
  try {
    const raw = window.localStorage.getItem(hiddenHistoryStorageKey(workspace))
    const parsed = raw ? JSON.parse(raw) : []
    return new Set(Array.isArray(parsed) ? parsed.filter(value => typeof value === 'string') : [])
  } catch {
    return new Set()
  }
}

function writeHiddenHistory(workspace: string, ids: Set<string>): void {
  try {
    const key = hiddenHistoryStorageKey(workspace)
    if (ids.size) window.localStorage.setItem(key, JSON.stringify([...ids]))
    else window.localStorage.removeItem(key)
  } catch {
    // Hiding history is still useful for the current session if storage is
    // blocked (private browsing, disabled cookies, or a quota error).
  }
}

function generationRecipe(task: CanonicalTask): string {
  const metadata = task.metadata || {}
  const details = (metadata.generation_details || metadata.settings || {}) as Record<string, unknown>
  const parts = [task.provider, task.model].filter(Boolean) as string[]
  const addModel = (label: string, value: unknown) => {
    if (!value) return
    const model = String(value)
    if (!parts.some(part => part === model || part.endsWith(` ${model}`))) {
      parts.push(label ? `${label} ${model}` : model)
    }
  }
  addModel('', details.model_name || details.model_type)
  addModel('text', details.text_model)
  addModel('image', details.image_model_name || details.image_model_type)
  addModel('video', details.video_model_name || details.video_model_type)
  const resolution = details.video_resolution || details.image_resolution || details.resolution
  const seed = details.seed
  const steps = details.video_steps || details.image_steps || details.steps || details.numInferenceSteps
  if (resolution) parts.push(String(resolution))
  if (seed !== undefined) parts.push(`seed ${seed}`)
  if (steps !== undefined) parts.push(`${steps} steps`)
  if (details.guidance !== undefined) parts.push(`guidance ${details.guidance}`)
  if (details.frames !== undefined) parts.push(`${details.frames} frames`)
  if (details.duration_seconds !== undefined) parts.push(`${details.duration_seconds}s`)
  if (details.dialogue_syllables !== undefined) {
    parts.push(
      `dialogue ${details.dialogue_syllables} syllables × ${details.dialogue_seconds_per_syllable}s → ${details.dialogue_duration_calculated}s calculated`
      + (details.dialogue_duration_minimum_limited ? ' · H3 minimum applied' : ''),
    )
  } else if (details.dialogue_words !== undefined) {
    parts.push(
      `dialogue ${details.dialogue_words} words → ${details.dialogue_duration_calculated}s calculated`
      + (details.dialogue_duration_minimum_limited ? ' · H3 minimum applied' : ''),
    )
  }
  if (details.profile) parts.push(`profile ${details.profile}`)
  if (details.flow_shift !== undefined || details.flowShift !== undefined) {
    parts.push(`flow shift ${details.flow_shift ?? details.flowShift}`)
  }
  if (details.audio_shift !== undefined || details.audioShift !== undefined) {
    parts.push(`audio shift ${details.audio_shift ?? details.audioShift}`)
  }
  if (details.turbo !== undefined) parts.push(`Turbo ${details.turbo ? 'on' : 'off'}`)
  if (details.cache !== undefined) {
    parts.push(details.cache
      ? `Cache on${details.cache_type ? ` (${details.cache_type})` : ''}`
      : 'Cache off')
  }
  if (details.lora_count !== undefined) {
    const loras = Array.isArray(details.loras) ? details.loras.map(String).filter(Boolean) : []
    parts.push(details.lora_count
      ? `${details.lora_count} LoRA${Number(details.lora_count) === 1 ? '' : 's'}${loras.length ? ` (${loras.join(', ')})` : ''}`
      : 'LoRAs off')
  }
  if (details.clip_count !== undefined) parts.push(`${details.clip_count} clips`)
  return parts.join(' · ')
}

export function ActivityFooter() {
  const activeWorkspace = useStore(state => state.activeWorkspace)
  const workspaceRef = useRef(activeWorkspace)
  workspaceRef.current = activeWorkspace
  const setVideoWorkflowsOpen = useStore(state => state.setDashboardOpen)
  const [tasks, setTasks] = useState<CanonicalTask[]>([])
  const tasksRef = useRef<CanonicalTask[]>([])
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [agentOpen, setAgentOpen] = useState(false)
  const [clock, setClock] = useState(Date.now())
  const [busyIds, setBusyIds] = useState<Set<string>>(() => new Set())
  const [controlFailures, setControlFailures] = useState<Record<string, TaskControlFailure>>({})
  const [hiddenHistoryIds, setHiddenHistoryIds] = useState<Set<string>>(() => new Set())
  const hiddenHistoryIdsRef = useRef<Set<string>>(new Set())

  useEffect(() => {
    const loaded = readHiddenHistory(activeWorkspace)
    hiddenHistoryIdsRef.current = loaded
    setHiddenHistoryIds(loaded)
  }, [activeWorkspace])

  useEffect(() => listenForAgentActivityDetails(() => setDetailsOpen(true)), [])

  useEffect(() => {
    let mounted = true
    let refreshPending = false
    let streamConnected = false
    let pollTimer: number | null = null
    let closeEvents: () => void = () => undefined
    let unknownTaskBaseline = 0

    const commitTasks = (next: CanonicalTask[]) => {
      tasksRef.current = next
      setTasks(next)
    }
    const refresh = async (): Promise<number | null> => {
      if (refreshPending) return null
      refreshPending = true
      try {
        const result = await api.fetchCanonicalTasks(activeWorkspace, 'all')
        if (mounted) {
          const snapshotBoundary = Math.max(
            unknownTaskBaseline,
            ...result.tasks.map(task => Number(task.updated_at || 0)),
          )
          unknownTaskBaseline = snapshotBoundary
          commitTasks(reconcileCanonicalTaskSnapshot(
            tasksRef.current,
            result.tasks,
            snapshotBoundary,
          ))
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
    setControlFailures({})
    void connectAfterSnapshot()
    return () => {
      mounted = false
      closeEvents()
      if (pollTimer !== null) window.clearTimeout(pollTimer)
    }
  }, [activeWorkspace])

  const roots = useMemo(() => {
    // Clear history is a UI-only filter. Active tasks always remain visible,
    // even if their id was previously hidden after an earlier completion.
    const visibleTasks = tasks.filter(task => !hiddenHistoryIds.has(task.id) || ACTIVE.has(task.status))
    const rootTasks = visibleTasks.filter(task => !task.parent_id)
    const active = rootTasks.filter(task => ACTIVE.has(task.status))
      .sort((left, right) => activityMoment(right) - activityMoment(left))
    const recent = rootTasks.filter(task => !ACTIVE.has(task.status))
      .sort((left, right) => activityMoment(right) - activityMoment(left))
      .slice(0, 12)
    return [...active, ...recent]
  }, [hiddenHistoryIds, tasks])
  const childrenByRoot = useMemo(() => {
    const result = new Map<string, CanonicalTask[]>()
    const visibleTasks = tasks.filter(task => !hiddenHistoryIds.has(task.id) || ACTIVE.has(task.status))
    for (const task of visibleTasks) {
      if (!task.parent_id) continue
      const children = result.get(task.root_id) || []
      children.push(task)
      result.set(task.root_id, children)
    }
    for (const children of result.values()) children.sort((a, b) => a.created_at - b.created_at)
    return result
  }, [hiddenHistoryIds, tasks])
  const activeTasks = roots.filter(task => ACTIVE.has(task.status))
  const historicalTasks = roots.filter(task => !ACTIVE.has(task.status))
  // With no active work, show what most recently happened. A days-old failure
  // must not mask a newer successful song/render merely because recovery
  // refreshed the old record's updated_at timestamp.
  const primary = activeTasks[0] || roots[0] || null

  const clearHistory = () => {
    const next = new Set(hiddenHistoryIdsRef.current)
    // Only terminal entries are hidden. No API call is made and generated
    // videos, metadata, and resumable server tasks remain untouched.
    for (const task of tasksRef.current) {
      if (!ACTIVE.has(task.status)) next.add(task.id)
    }
    hiddenHistoryIdsRef.current = next
    setHiddenHistoryIds(next)
    writeHiddenHistory(activeWorkspace, next)
    if (!activeTasks.length) setDetailsOpen(false)
  }

  useEffect(() => {
    if (!activeTasks.length) return
    const timer = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [activeTasks.length])

  const runControl = (task: CanonicalTask, action: TaskControlAction) => {
    if (busyIds.has(task.id)) return
    const workspace = activeWorkspace
    const taskId = task.id
    setBusyIds(current => new Set(current).add(taskId))
    const operation = action === 'cancel'
      ? api.cancelCanonicalTask(taskId, workspace)
      : action === 'resume'
        ? api.resumeCanonicalTask(taskId, workspace)
        : api.dismissCanonicalTask(taskId, workspace)
    void operation.then(result => {
      if (workspaceRef.current !== workspace) return
      const next = action === 'dismiss'
        ? tasksRef.current.filter(item => item.id !== taskId)
        : tasksRef.current.map(item => item.id === taskId ? result as CanonicalTask : item)
      tasksRef.current = next
      setTasks(next)
      setControlFailures(current => {
        if (!current[taskId]) return current
        const nextFailures = { ...current }
        delete nextFailures[taskId]
        return nextFailures
      })
    }).catch(reason => {
      if (workspaceRef.current !== workspace) return
      const message = reason instanceof Error ? reason.message : String(reason)
      setControlFailures(current => ({
        ...current,
        [taskId]: { action, message },
      }))
      // A footer-level Cancel can fail while the task list is collapsed. Open
      // it so the actionable error and Retry control are immediately visible.
      setDetailsOpen(true)
    }).finally(() => {
      setBusyIds(current => {
        const next = new Set(current)
        next.delete(taskId)
        return next
      })
    })
  }

  const copyId = (task: CanonicalTask) => {
    void navigator.clipboard?.writeText(task.id)
  }

  const isActive = activeTasks.length > 0
  const hasError = !isActive && (primary?.status === 'failed' || primary?.status === 'interrupted')
  const primaryVisualState = primary ? canonicalTaskVisualState(primary.status) : 'neutral'
  const primaryMessage = primary?.error?.message || primary?.detail || primary?.message || 'Ready — no active jobs'
  const primaryEta = primary ? formatEta(estimatedRemainingSeconds(primary, clock)) : ''
  const primaryActiveChild = primary
    ? (childrenByRoot.get(primary.root_id) || []).find(child => ACTIVE.has(child.status))
    : undefined
  const primaryChildEta = primaryActiveChild
    ? formatEta(estimatedRemainingSeconds(primaryActiveChild, clock))
    : ''

  return (
    <footer className="relative h-10 shrink-0 border-t border-border bg-bg-secondary px-3 sm:px-4 flex items-center gap-3 text-[10px] z-40">
      {agentOpen && (
        <Suspense fallback={null}>
          <AgentAssistantPanel
            workspace={activeWorkspace}
            tasks={tasks}
            onClose={() => setAgentOpen(false)}
          />
        </Suspense>
      )}
      {detailsOpen && roots.length > 0 && (
        <div className="absolute bottom-full left-3 mb-2 w-[min(48rem,calc(100vw-1.5rem))] max-h-80 overflow-y-auto rounded-lg border border-border bg-bg-secondary p-2 shadow-2xl">
          <div className="mb-1.5 flex items-center justify-between px-1">
            <span className="font-semibold text-text-primary">HocusPocus tasks</span>
            <div className="flex items-center gap-2">
              {historicalTasks.length > 0 && (
                <button
                  type="button"
                  onClick={clearHistory}
                  className="flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted hover:text-text-primary"
                  title="Hide completed task history from this UI. Videos and task data are kept."
                  aria-label="Clear activity history"
                >
                  <Eraser size={10} /> Clear history
                </button>
              )}
              <span className="text-text-muted">{activeTasks.length} active · durable per workspace</span>
            </div>
          </div>
          <div className="space-y-1.5">
            {roots.map(task => {
              const taskChildren = childrenByRoot.get(task.root_id) || []
              const activeChild = taskChildren.find(child => ACTIVE.has(child.status))
              const active = ACTIVE.has(task.status)
              const recipe = generationRecipe(task)
              const visualState = canonicalTaskVisualState(task.status)
              const controlFailure = controlFailures[task.id]
              const updatedAt = formatAppTimestamp(task.updated_at)
              const taskEta = formatEta(estimatedRemainingSeconds(task, clock))
              return (
                <div key={task.id} className="rounded-md border border-border bg-bg-primary p-2">
                  <div className="flex items-start gap-2">
                    {visualState === 'active'
                      ? <Loader2 size={12} className="mt-0.5 shrink-0 animate-spin text-accent-blue" />
                      : visualState === 'error'
                        ? <AlertCircle size={12} className="mt-0.5 shrink-0 text-red-400" />
                        : visualState === 'cancelled'
                          ? <CircleSlash2 size={12} className="mt-0.5 shrink-0 text-text-muted" />
                          : <CheckCircle2 size={12} className="mt-0.5 shrink-0 text-emerald-400" />}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium text-text-primary">{task.title}</span>
                        <div className="flex items-center gap-2">
                          <span className="tabular-nums text-text-muted" title={updatedAt ? `${formatAppAction('updated')}: ${updatedAt}` : undefined}>{elapsed(task, clock)}</span>
                          {active && taskEta && <span className="tabular-nums text-accent-blue" title="Estimated remaining time for the complete task">ETA {taskEta}</span>}
                          {updatedAt && <span className="hidden md:inline text-text-muted">{updatedAt}</span>}
                          <span className="capitalize text-text-muted">{phaseLabel(task)}</span>
                          {active && task.cancelable && (
                            <button type="button" disabled={busyIds.has(task.id)} onClick={() => runControl(task, 'cancel')} className="rounded border border-red-400/40 px-1.5 py-0.5 text-[9px] text-red-300">
                              {busyIds.has(task.id) ? 'Cancelling…' : 'Cancel'}
                            </button>
                          )}
                          {!active && canResumeCanonicalTask(task) && (
                            <button type="button" disabled={busyIds.has(task.id)} onClick={() => runControl(task, 'resume')} className="rounded border border-border px-1.5 py-0.5 text-[9px] text-accent-blue">Resume</button>
                          )}
                          {!active && (
                            <button type="button" disabled={busyIds.has(task.id)} onClick={() => runControl(task, 'dismiss')} className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted">Dismiss</button>
                          )}
                        </div>
                      </div>
                      <p className={task.status === 'failed' || task.status === 'interrupted' ? 'text-red-400' : 'text-text-secondary'} title={task.detail || task.message}>
                        {task.error?.message || task.detail || task.message}
                      </p>
                      {recipe && <p className="mt-0.5 break-words text-[9px] text-amber-300">{recipe}</p>}
                      {resources(task) && <p className="text-[9px] text-accent-blue">{resources(task)}</p>}
                      {active && activeChild && (
                        <p className="text-[9px] text-violet-300">
                          Active subtask: {phaseLabel(activeChild)}
                          {formatEta(estimatedRemainingSeconds(activeChild, clock)) && ` · ETA ${formatEta(estimatedRemainingSeconds(activeChild, clock))}`}
                        </p>
                      )}
                      {controlFailure && (
                        <div aria-live="polite" className="mt-1.5 flex items-center justify-between gap-2 rounded border border-red-400/40 bg-red-500/10 px-2 py-1 text-[9px] text-red-300">
                          <span>{controlFailure.action[0].toUpperCase() + controlFailure.action.slice(1)} failed: {controlFailure.message}</span>
                          <button
                            type="button"
                            disabled={busyIds.has(task.id)}
                            onClick={() => runControl(task, controlFailure.action)}
                            className="shrink-0 rounded border border-red-300/50 px-1.5 py-0.5 font-medium disabled:opacity-50"
                            aria-label={`Retry ${controlFailure.action}`}
                          >
                            Retry
                          </button>
                        </div>
                      )}
                      <p className="mt-0.5 flex flex-wrap gap-x-2 text-[9px] text-text-muted">
                        {task.server_origin && <span>server {task.server_origin}</span>}
                        <span>attempt {task.attempt}/{task.max_attempts}</span>
                        {!!task.token_usage?.total && <span>{task.token_usage.total.toLocaleString()} tokens · {task.token_usage.prompt || 0} input · {task.token_usage.completion || 0} output</span>}
                        <button type="button" onClick={() => copyId(task)} className="font-mono hover:text-text-primary" title="Copy task ID">{task.id}</button>
                      </p>
                      {taskChildren.length > 0 && (
                        <div className="mt-1 border-l border-border pl-2 text-[9px] text-text-muted">
                          {taskChildren.map(child => {
                            const childRecipe = generationRecipe(child)
                            const childResources = resources(child)
                            return (
                              <div key={child.id} className="mb-1 last:mb-0" title={child.detail || child.message}>
                                <p>
                                  {phaseLabel(child)} · {elapsed(child, clock)} · {child.message}
                                  {ACTIVE.has(child.status) && formatEta(estimatedRemainingSeconds(child, clock)) && ` · ETA ${formatEta(estimatedRemainingSeconds(child, clock))}`}
                                </p>
                                <p className="flex flex-wrap gap-x-2 text-[8px] text-text-muted">
                                  {childRecipe && <span className="text-amber-300">{childRecipe}</span>}
                                  {child.server_origin && <span>server {child.server_origin}</span>}
                                  {childResources && <span className="text-accent-blue">{childResources}</span>}
                                  <span>attempt {child.attempt}/{child.max_attempts}</span>
                                  {!!child.token_usage?.total && (
                                    <span>
                                      {child.token_usage.total.toLocaleString()} tokens · {child.token_usage.prompt || 0} input · {child.token_usage.completion || 0} output
                                    </span>
                                  )}
                                  <button type="button" onClick={() => copyId(child)} className="font-mono hover:text-text-primary" title="Copy child task ID">
                                    {child.id}
                                  </button>
                                </p>
                              </div>
                            )
                          })}
                        </div>
                      )}
                      {active && (
                        <div className="mt-1.5 flex items-center gap-2">
                          <div className="h-1 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
                            <div className="h-full rounded-full bg-accent-blue transition-[width] duration-300" style={{ width: `${Math.max(percent(task), percent(task) > 0 ? 2 : 0)}%` }} />
                          </div>
                          <span className="w-12 text-right tabular-nums text-text-muted">{task.total > 0 ? `${task.current}/${task.total}` : `${Math.round(percent(task))}%`}</span>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="flex h-full w-44 shrink-0 items-center border-r border-amber-200/15 pr-3">
        <button
          type="button"
          onClick={() => { setAgentOpen(open => !open); setDetailsOpen(false) }}
          className={`hp-agent-trigger flex w-full items-center gap-2 rounded-lg border px-2 py-0.5 text-left transition ${agentOpen ? 'border-amber-200/45 bg-amber-200/10 text-amber-50' : 'border-amber-200/15 bg-amber-100/[.025] text-amber-100/75 hover:border-amber-200/35 hover:bg-amber-100/[.055] hover:text-amber-50'}`}
          aria-expanded={agentOpen}
          title="Ask to the Wizard about the app or current task queue"
        >
          <AgentAvatar state={agentOpen ? 'listening' : 'idle'} size={24} />
          <span className="font-medium whitespace-nowrap">Ask to the Wizard</span>
        </button>
      </div>

      <button type="button" onClick={() => { setDetailsOpen(open => !open); setAgentOpen(false) }} className="flex items-center gap-1.5 shrink-0" aria-expanded={detailsOpen} title="Show canonical task history">
        {isActive
          ? <Loader2 size={13} className="animate-spin text-accent-blue" />
          : hasError
            ? <AlertCircle size={13} className="text-red-400" />
            : primaryVisualState === 'cancelled'
              ? <CircleSlash2 size={13} className="text-text-muted" />
              : <CheckCircle2 size={13} className="text-emerald-400" />}
        <span className="font-medium text-text-primary">Activity</span>
        {activeTasks.length > 0 && <span className="rounded-full bg-accent-blue/15 px-1.5 py-0.5 text-accent-blue tabular-nums">{activeTasks.length}</span>}
        {detailsOpen ? <ChevronDown size={11} /> : <ChevronUp size={11} />}
      </button>

      <div className="min-w-0 flex-1 flex items-center gap-2">
        {primary && <span className="hidden sm:inline shrink-0 capitalize text-text-muted">{phaseLabel(primary)}</span>}
        {primary && <span className="shrink-0 tabular-nums text-text-muted">{elapsed(primary, clock)}</span>}
        {primaryEta && <span className="hidden sm:inline shrink-0 tabular-nums text-accent-blue" title="Estimated remaining time for the complete task">ETA {primaryEta}</span>}
        {primaryActiveChild && <span className="hidden lg:inline shrink-0 max-w-56 truncate text-violet-300" title={`Active subtask: ${primaryActiveChild.message}`}>Subtask {phaseLabel(primaryActiveChild)}{primaryChildEta ? ` · ETA ${primaryChildEta}` : ''}</span>}
        {primary?.model && <span className="hidden md:inline max-w-64 shrink-0 truncate rounded border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-amber-300" title={generationRecipe(primary)}>{primary.model}</span>}
        <span className={`truncate ${hasError ? 'text-red-400' : isActive ? 'text-text-secondary' : 'text-text-muted'}`} title={primaryMessage}>{primaryMessage}</span>
      </div>

      {isActive && primary && (
        <div className="hidden sm:flex items-center gap-2 w-52 shrink-0">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
            <div className="h-full rounded-full bg-accent-blue transition-[width] duration-500" style={{ width: `${Math.max(percent(primary), percent(primary) > 0 ? 2 : 0)}%` }} />
          </div>
          <span className="w-10 text-right tabular-nums text-text-secondary">{primary.total > 0 ? `${primary.current}/${primary.total}` : `${Math.round(percent(primary))}%`}</span>
        </div>
      )}
      {primary && ACTIVE.has(primary.status) && primary.cancelable && (
        <button type="button" disabled={busyIds.has(primary.id)} onClick={() => runControl(primary, 'cancel')} className="flex shrink-0 items-center gap-1 rounded-md border border-red-400/40 px-2 py-1 text-red-300 disabled:opacity-50">
          {busyIds.has(primary.id) && <Loader2 size={11} className="animate-spin" />}
          <span>{busyIds.has(primary.id) ? 'Cancelling…' : 'Cancel'}</span>
        </button>
      )}
      <button onClick={() => {
        useStore.getState().setMediaFilter('workspaces')
        setVideoWorkflowsOpen(false)
      }} className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-text-secondary hover:border-accent-blue/50 hover:text-accent-blue transition-colors shrink-0" title="Open Workspaces to inspect prompts, references and the generation queue">
        <ListVideo size={12} /><span className="hidden sm:inline">Workspaces</span>
      </button>
    </footer>
  )
}
