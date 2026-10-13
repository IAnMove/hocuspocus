import { cancelCanonicalTask, fetchCanonicalTasks, resumeCanonicalTask, retryCanonicalTask, type CanonicalTask } from '../../api/client'
import i18n from '../../i18n'
import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import { canResumeCanonicalTask } from '../../lib/canonicalTaskEvents'
import { useStore } from '../../stores/useStore'

function queueResult(message: string, taskId?: string): CommandResult {
  const workspace = workspaceId()
  const entity = { kind: 'activity', id: taskId || 'activity', workspaceId: workspace }
  return commandResultFromSlice({
    entity,
    taskIds: taskId ? [taskId] : [],
    navigationTarget: { destination: 'activity', entity },
    artifacts: [{
      id: 'reply',
      kind: 'document',
      owner: entity,
      uri: 'queue:reply',
      metadata: { summary: message },
    }],
  })
}

const ACTIVE = new Set(['created', 'queued', 'waiting_resource', 'running'])

function workspaceId(): string {
  return useStore.getState().activeWorkspace || 'default'
}

function formatTaskLine(task: CanonicalTask): string {
  const percent = Math.round(Math.max(0, Math.min(1, Number(task.progress || 0))) * 100)
  const required = (task.resource_requirements || []).join(', ')
  const waiting = task.status === 'waiting_resource'
    ? i18n.t('studio:replies.taskWaiting', { resources: required || i18n.t('studio:replies.taskResource') })
    : ''
  const using = task.acquired_resources?.length
    ? i18n.t('studio:replies.taskUsing', { resources: task.acquired_resources.join(', ') })
    : ''
  const pipeline = task.pipeline_id ? ` Pipeline ${task.pipeline_id}.` : ''
  return `• ${task.title || task.kind} [${task.status}${percent ? ` ${percent}%` : ''}] ${task.id}.${pipeline}${waiting}${using}`
}

function resolveTask(tasks: CanonicalTask[], requestedId: string): CanonicalTask {
  const roots = tasks.filter(task => !task.parent_id)
  const needle = requestedId.trim()
  if (!needle || needle === 'active' || needle === 'current') {
    const active = roots.filter(task => ACTIVE.has(task.status))
    if (!active.length) throw new Error(i18n.t('studio:actionErrors.noActiveTask'))
    if (active.length > 1) {
      const list = active.slice(0, 8).map(task => `${task.id} (${task.title || task.kind})`).join('; ')
      throw new Error(i18n.t('studio:actionErrors.multipleActiveTasks', { count: active.length, list }))
    }
    return active[0]
  }
  const exact = tasks.find(task => task.id === needle)
  if (exact) return exact
  const exactBackend = tasks.filter(task => task.pipeline_id === needle || task.backend_job_id === needle)
  if (exactBackend.length === 1) return exactBackend[0]
  if (exactBackend.length > 1) throw new Error(i18n.t('studio:actionErrors.ambiguousTaskId', { id: needle }))
  const prefix = tasks.filter(task => task.id.startsWith(needle))
  if (prefix.length === 1) return prefix[0]
  throw new Error(i18n.t('studio:actionErrors.taskNotFound', { id: needle }))
}

function resolveRetryTask(tasks: CanonicalTask[], requestedId: string): CanonicalTask {
  const roots = tasks.filter(task => !task.parent_id && canResumeCanonicalTask(task))
  const needle = requestedId.trim()
  if (needle === 'latest') {
    const latest = [...roots].sort((left, right) => right.updated_at - left.updated_at)[0]
    if (!latest) throw new Error(i18n.t('studio:actionErrors.noRetryableFailure'))
    return latest
  }
  if (!needle) {
    if (!roots.length) throw new Error(i18n.t('studio:actionErrors.noRetryableTask'))
    if (roots.length > 1) {
      throw new Error(i18n.t('studio:actionErrors.multipleRetryableTasks', { count: roots.length }))
    }
    return roots[0]
  }
  const task = resolveTask(tasks, needle)
  if (!canResumeCanonicalTask(task)) {
    throw new Error(i18n.t('studio:actionErrors.taskNotRetryable', { id: task.id, status: task.status }))
  }
  return task
}

export async function inspectCanonicalQueue(scope: 'active' | 'all'): Promise<CommandResult> {
  const result = await fetchCanonicalTasks(workspaceId(), scope === 'all' ? 'all' : 'active')
  const roots = result.tasks.filter(task => !task.parent_id)
  const active = roots.filter(task => ACTIVE.has(task.status))
  if (!roots.length) {
    return queueResult(scope === 'all'
      ? i18n.t('studio:replies.queueEmptyAll')
      : i18n.t('studio:replies.queueEmptyActive'))
  }
  const waiting = active.filter(task => task.status === 'waiting_resource')
  const gpuWait = waiting.filter(task =>
    (task.resource_requirements || []).some(resource => /gpu/i.test(resource))
    || (task.acquired_resources || []).some(resource => /gpu/i.test(resource))
    || /gpu/i.test(task.message || ''),
  )
  const lines = (scope === 'all' ? roots.slice(0, 12) : active).map(formatTaskLine)
  const gpuNames = gpuWait.map(task => task.title || task.id).join(', ')
  const waitNote = gpuWait.length
    ? i18n.t('studio:replies.gpuBusy', { names: gpuNames })
    : waiting.length
      ? i18n.t('studio:replies.resourceWait', { count: waiting.length })
      : ''
  return queueResult(i18n.t('studio:replies.queueSummary', {
    scope,
    active: active.length,
    visible: roots.length,
    waitNote,
    lines: lines.join('\n'),
  }))
}

export async function cancelCanonicalQueueTask(taskId: string, confirm: boolean): Promise<CommandResult> {
  if (!confirm) throw new Error(i18n.t('studio:actionErrors.cancelNeedsConfirm'))
  const snapshot = await fetchCanonicalTasks(workspaceId(), 'all')
  const task = resolveTask(snapshot.tasks, taskId)
  if (!task.cancelable || !ACTIVE.has(task.status)) {
    throw new Error(i18n.t('studio:actionErrors.taskNotCancelable', { id: task.id, status: task.status }))
  }
  const cancelled = await cancelCanonicalTask(task.id, workspaceId())
  const backendJobId = cancelled.backend_job_id || task.backend_job_id
  const adapter = String(cancelled.metadata?.adapter || task.metadata?.adapter || '')
  if (backendJobId && adapter !== 'director') useStore.getState().stopGeneration(backendJobId)
  if (adapter === 'director') {
    const pipelineId = cancelled.pipeline_id || task.pipeline_id || backendJobId
    if (pipelineId && useStore.getState().pipelineId === pipelineId) {
      useStore.setState({ pipelineId: null, pipelineStatus: null, pipelinePolling: false, directorLoading: false })
    }
    void useStore.getState().loadPipelineList(pipelineId || undefined)
  }
  const title = cancelled.title || task.title
  return queueResult(
    i18n.t('studio:replies.cancelRequested', { title, id: cancelled.id, status: cancelled.status }),
    cancelled.id,
  )
}

export async function resumeCanonicalQueueTask(taskId: string, confirm: boolean): Promise<CommandResult> {
  if (!confirm) throw new Error(i18n.t('studio:actionErrors.resumeNeedsConfirm'))
  const snapshot = await fetchCanonicalTasks(workspaceId(), 'all')
  const task = resolveTask(snapshot.tasks, taskId)
  if (!canResumeCanonicalTask(task)) {
    throw new Error(i18n.t('studio:actionErrors.taskNotResumable', { id: task.id, status: task.status }))
  }
  const resumed = await resumeCanonicalTask(task.id, workspaceId())
  const adapter = String(resumed.metadata?.adapter || task.metadata?.adapter || '')
  const pipelineId = resumed.pipeline_id || task.pipeline_id || resumed.backend_job_id || task.backend_job_id
  if (adapter === 'director' && pipelineId) {
    useStore.setState({
      pipelineId,
      pipelineStatus: null,
      pipelinePolling: true,
      directorLoading: true,
      directorError: null,
    })
    useStore.getState().pollPipelineStatus()
    void useStore.getState().loadSavedPipeline(pipelineId)
    void useStore.getState().loadPipelineList(pipelineId)
  }
  const title = resumed.title || task.title
  return queueResult(
    i18n.t('studio:replies.resumed', { title, id: resumed.id, status: resumed.status }),
    resumed.id,
  )
}

export async function retryCanonicalQueueTask(taskId: string, confirm: boolean): Promise<CommandResult> {
  if (!confirm) throw new Error(i18n.t('studio:actionErrors.retryNeedsConfirm'))
  const snapshot = await fetchCanonicalTasks(workspaceId(), 'all')
  const task = resolveRetryTask(snapshot.tasks, taskId)
  const retried = await retryCanonicalTask(task.id, workspaceId())
  const title = retried.title || task.title
  return queueResult(
    i18n.t('studio:replies.retried', { title, id: retried.id, status: retried.status }),
    retried.id,
  )
}
