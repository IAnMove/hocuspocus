import { useEffect, useMemo, useState } from 'react'
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, ListVideo, Loader2 } from 'lucide-react'
import * as api from '../api/client'
import type { CanonicalTask } from '../api/client'
import { useStore } from '../stores/useStore'

const ACTIVE = new Set(['created', 'queued', 'waiting_resource', 'running'])
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
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  interrupted: 'Interrupted',
}

function epochMs(value?: number | null): number | undefined {
  if (!value || !Number.isFinite(value)) return undefined
  return value < 1_000_000_000_000 ? value * 1000 : value
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

function percent(task: CanonicalTask): number {
  if (task.total > 0) return Math.max(0, Math.min(100, (task.current / task.total) * 100))
  return Math.max(0, Math.min(100, Number(task.progress || 0) * 100))
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

function generationRecipe(task: CanonicalTask): string {
  const metadata = task.metadata || {}
  const details = (metadata.generation_details || metadata.settings || {}) as Record<string, unknown>
  const parts = [task.provider, task.model].filter(Boolean) as string[]
  const resolution = details.video_resolution || details.image_resolution || details.resolution
  const seed = details.seed
  const steps = details.video_steps || details.image_steps || details.steps || details.numInferenceSteps
  if (resolution) parts.push(String(resolution))
  if (seed !== undefined) parts.push(`seed ${seed}`)
  if (steps !== undefined) parts.push(`${steps} steps`)
  if (details.frames !== undefined) parts.push(`${details.frames} frames`)
  if (details.flow_shift !== undefined || details.flowShift !== undefined) {
    parts.push(`flow shift ${details.flow_shift ?? details.flowShift}`)
  }
  if (details.audio_shift !== undefined || details.audioShift !== undefined) {
    parts.push(`audio shift ${details.audio_shift ?? details.audioShift}`)
  }
  if (details.dialogue_words !== undefined) {
    parts.push(
      `dialogue ${details.dialogue_words} words → ${details.dialogue_duration_calculated}s calculated`
      + (details.dialogue_duration_minimum_limited ? ' · H3 minimum applied' : ''),
    )
  }
  return parts.join(' · ')
}

export function ActivityFooter() {
  const activeWorkspace = useStore(state => state.activeWorkspace)
  const setVideoWorkflowsOpen = useStore(state => state.setDashboardOpen)
  const [tasks, setTasks] = useState<CanonicalTask[]>([])
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [clock, setClock] = useState(Date.now())
  const [busyIds, setBusyIds] = useState<Set<string>>(() => new Set())

  useEffect(() => {
    let mounted = true
    let refreshPending = false
    const refresh = async () => {
      if (refreshPending) return
      refreshPending = true
      try {
        const result = await api.fetchCanonicalTasks(activeWorkspace, 'all')
        if (mounted) setTasks(result.tasks)
      } catch {
        // Polling below remains the fallback while the backend is restarting.
      } finally {
        refreshPending = false
      }
    }
    void refresh()
    const closeEvents = api.subscribeCanonicalTaskEvents(
      activeWorkspace,
      () => { void refresh() },
      () => undefined,
    )
    const poll = window.setInterval(() => { void refresh() }, 2000)
    return () => {
      mounted = false
      closeEvents()
      window.clearInterval(poll)
    }
  }, [activeWorkspace])

  const roots = useMemo(() => {
    const rootTasks = tasks.filter(task => !task.parent_id)
    const active = rootTasks.filter(task => ACTIVE.has(task.status))
      .sort((left, right) => right.updated_at - left.updated_at)
    const recent = rootTasks.filter(task => !ACTIVE.has(task.status))
      .sort((left, right) => right.updated_at - left.updated_at)
      .slice(0, 12)
    return [...active, ...recent]
  }, [tasks])
  const childrenByRoot = useMemo(() => {
    const result = new Map<string, CanonicalTask[]>()
    for (const task of tasks) {
      if (!task.parent_id) continue
      const children = result.get(task.root_id) || []
      children.push(task)
      result.set(task.root_id, children)
    }
    for (const children of result.values()) children.sort((a, b) => a.created_at - b.created_at)
    return result
  }, [tasks])
  const activeTasks = roots.filter(task => ACTIVE.has(task.status))
  const failedTasks = roots.filter(task => task.status === 'failed' || task.status === 'interrupted')
  const primary = activeTasks[0] || failedTasks[0] || roots[0] || null

  useEffect(() => {
    if (!activeTasks.length) return
    const timer = window.setInterval(() => setClock(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [activeTasks.length])

  const runControl = (task: CanonicalTask, action: 'cancel' | 'resume' | 'dismiss') => {
    if (busyIds.has(task.id)) return
    setBusyIds(current => new Set(current).add(task.id))
    const operation = action === 'cancel'
      ? api.cancelCanonicalTask(task.id, activeWorkspace)
      : action === 'resume'
        ? api.resumeCanonicalTask(task.id, activeWorkspace)
        : api.dismissCanonicalTask(task.id, activeWorkspace)
    void operation.then(async () => {
      const result = await api.fetchCanonicalTasks(activeWorkspace, 'all')
      setTasks(result.tasks)
    }).catch(error => console.error(`Failed to ${action} Maestro task`, error)).finally(() => {
      setBusyIds(current => {
        const next = new Set(current)
        next.delete(task.id)
        return next
      })
    })
  }

  const copyId = (task: CanonicalTask) => {
    void navigator.clipboard?.writeText(task.id)
  }

  const isActive = activeTasks.length > 0
  const hasError = !isActive && failedTasks.length > 0
  const primaryMessage = primary?.error?.message || primary?.detail || primary?.message || 'Ready — no active jobs'

  return (
    <footer className="relative h-10 shrink-0 border-t border-border bg-bg-secondary px-3 sm:px-4 flex items-center gap-3 text-[10px] z-40">
      {detailsOpen && roots.length > 0 && (
        <div className="absolute bottom-full left-3 mb-2 w-[min(48rem,calc(100vw-1.5rem))] max-h-80 overflow-y-auto rounded-lg border border-border bg-bg-secondary p-2 shadow-2xl">
          <div className="mb-1.5 flex items-center justify-between px-1">
            <span className="font-semibold text-text-primary">Maestro tasks</span>
            <span className="text-text-muted">{activeTasks.length} active · durable per workspace</span>
          </div>
          <div className="space-y-1.5">
            {roots.map(task => {
              const taskChildren = childrenByRoot.get(task.root_id) || []
              const active = ACTIVE.has(task.status)
              const recipe = generationRecipe(task)
              return (
                <div key={task.id} className="rounded-md border border-border bg-bg-primary p-2">
                  <div className="flex items-start gap-2">
                    {active
                      ? <Loader2 size={12} className="mt-0.5 shrink-0 animate-spin text-accent-blue" />
                      : task.status === 'failed' || task.status === 'interrupted'
                        ? <AlertCircle size={12} className="mt-0.5 shrink-0 text-red-400" />
                        : <CheckCircle2 size={12} className="mt-0.5 shrink-0 text-emerald-400" />}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span className="font-medium text-text-primary">{task.title}</span>
                        <div className="flex items-center gap-2">
                          <span className="tabular-nums text-text-muted">{elapsed(task, clock)}</span>
                          <span className="capitalize text-text-muted">{phaseLabel(task)}</span>
                          {active && task.cancelable && (
                            <button type="button" disabled={busyIds.has(task.id)} onClick={() => runControl(task, 'cancel')} className="rounded border border-red-400/40 px-1.5 py-0.5 text-[9px] text-red-300">
                              {busyIds.has(task.id) ? 'Cancelling…' : 'Cancel'}
                            </button>
                          )}
                          {!active && task.resumable && (
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
                      <p className="mt-0.5 flex flex-wrap gap-x-2 text-[9px] text-text-muted">
                        {task.server_origin && <span>server {task.server_origin}</span>}
                        <span>attempt {task.attempt}/{task.max_attempts}</span>
                        {!!task.token_usage?.total && <span>{task.token_usage.total.toLocaleString()} tokens · {task.token_usage.prompt || 0} input · {task.token_usage.completion || 0} output</span>}
                        <button type="button" onClick={() => copyId(task)} className="font-mono hover:text-text-primary" title="Copy task ID">{task.id}</button>
                      </p>
                      {taskChildren.length > 0 && (
                        <div className="mt-1 border-l border-border pl-2 text-[9px] text-text-muted">
                          {taskChildren.map(child => (
                            <p key={child.id} title={child.detail || child.message}>
                              {phaseLabel(child)} · {child.provider || 'local'}{child.model ? ` / ${child.model}` : ''} · {elapsed(child, clock)} · {child.message}
                            </p>
                          ))}
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

      <button type="button" onClick={() => setDetailsOpen(open => !open)} className="flex items-center gap-1.5 shrink-0" aria-expanded={detailsOpen} title="Show canonical task history">
        {isActive ? <Loader2 size={13} className="animate-spin text-accent-blue" /> : hasError ? <AlertCircle size={13} className="text-red-400" /> : <CheckCircle2 size={13} className="text-emerald-400" />}
        <span className="font-medium text-text-primary">Activity</span>
        {activeTasks.length > 0 && <span className="rounded-full bg-accent-blue/15 px-1.5 py-0.5 text-accent-blue tabular-nums">{activeTasks.length}</span>}
        {detailsOpen ? <ChevronDown size={11} /> : <ChevronUp size={11} />}
      </button>

      <div className="min-w-0 flex-1 flex items-center gap-2">
        {primary && <span className="hidden sm:inline shrink-0 capitalize text-text-muted">{phaseLabel(primary)}</span>}
        {primary && <span className="shrink-0 tabular-nums text-text-muted">{elapsed(primary, clock)}</span>}
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
      <button onClick={() => setVideoWorkflowsOpen(true)} className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-text-secondary hover:border-accent-blue/50 hover:text-accent-blue transition-colors shrink-0" title="Open independent video creations and edit their clips">
        <ListVideo size={12} /><span className="hidden sm:inline">Video workflows</span>
      </button>
    </footer>
  )
}
