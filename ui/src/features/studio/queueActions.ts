import { cancelCanonicalTask, fetchCanonicalTasks, resumeCanonicalTask, retryCanonicalTask, type CanonicalTask } from '../../api/client'
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
  const waiting = task.status === 'waiting_resource'
    ? ` Waiting for ${((task.resource_requirements || []).join(', ') || 'a resource')}.`
    : ''
  const using = task.acquired_resources?.length ? ` Usa ${task.acquired_resources.join(', ')}.` : ''
  const pipeline = task.pipeline_id ? ` Pipeline ${task.pipeline_id}.` : ''
  return `• ${task.title || task.kind} [${task.status}${percent ? ` ${percent}%` : ''}] ${task.id}.${pipeline}${waiting}${using}`
}

function resolveTask(tasks: CanonicalTask[], requestedId: string): CanonicalTask {
  const roots = tasks.filter(task => !task.parent_id)
  const needle = requestedId.trim()
  if (!needle || needle === 'active' || needle === 'current') {
    const active = roots.filter(task => ACTIVE.has(task.status))
    if (!active.length) throw new Error('There is no active task to select.')
    if (active.length > 1) {
      throw new Error(
        `There are ${active.length} active tasks; give the id. `
        + active.slice(0, 8).map(task => `${task.id} (${task.title || task.kind})`).join('; '),
      )
    }
    return active[0]
  }
  const exact = tasks.find(task => task.id === needle)
  if (exact) return exact
  const exactBackend = tasks.filter(task => task.pipeline_id === needle || task.backend_job_id === needle)
  if (exactBackend.length === 1) return exactBackend[0]
  if (exactBackend.length > 1) throw new Error(`The identifier “${needle}” matches several tasks; use the canonical id.`)
  const prefix = tasks.filter(task => task.id.startsWith(needle))
  if (prefix.length === 1) return prefix[0]
  throw new Error(`I couldn't find the task “${needle}” in the canonical queue.`)
}

function resolveRetryTask(tasks: CanonicalTask[], requestedId: string): CanonicalTask {
  const roots = tasks.filter(task => !task.parent_id && canResumeCanonicalTask(task))
  const needle = requestedId.trim()
  if (needle === 'latest') {
    const latest = [...roots].sort((left, right) => right.updated_at - left.updated_at)[0]
    if (!latest) throw new Error('There is no failed, cancelled or interrupted task to retry.')
    return latest
  }
  if (!needle) {
    if (!roots.length) throw new Error('There is no retryable task.')
    if (roots.length > 1) {
      throw new Error(`There are ${roots.length} retryable tasks; give the id or explicitly ask for “the last failure”.`)
    }
    return roots[0]
  }
  const task = resolveTask(tasks, needle)
  if (!canResumeCanonicalTask(task)) {
    throw new Error(`Task ${task.id} cannot be retried now (${task.status}).`)
  }
  return task
}

export async function inspectCanonicalQueue(scope: 'active' | 'all'): Promise<CommandResult> {
  const result = await fetchCanonicalTasks(workspaceId(), scope === 'all' ? 'all' : 'active')
  const roots = result.tasks.filter(task => !task.parent_id)
  const active = roots.filter(task => ACTIVE.has(task.status))
  if (!roots.length) {
    return queueResult(scope === 'all'
      ? 'This workspace\'s canonical queue is empty. I opened the Activity history.'
      : 'There are no active tasks. I opened Activity in case you want to see the history.')
  }
  const waiting = active.filter(task => task.status === 'waiting_resource')
  const gpuWait = waiting.filter(task =>
    (task.resource_requirements || []).some(resource => /gpu/i.test(resource))
    || (task.acquired_resources || []).some(resource => /gpu/i.test(resource))
    || /gpu/i.test(task.message || ''),
  )
  const lines = (scope === 'all' ? roots.slice(0, 12) : active).map(formatTaskLine)
  const waitNote = gpuWait.length
    ? ` The GPU is busy or pending: ${gpuWait.map(task => task.title || task.id).join(', ')}.`
    : waiting.length
      ? ` ${waiting.length} task(s) waiting for a resource.`
      : ''
  return queueResult(`Queue ${scope}: ${active.length} active of ${roots.length} visible.${waitNote} I opened Activity.\n${lines.join('\n')}`)
}

export async function cancelCanonicalQueueTask(taskId: string, confirm: boolean): Promise<CommandResult> {
  if (!confirm) throw new Error('Cancelling requires confirm=true after an explicit user request.')
  const snapshot = await fetchCanonicalTasks(workspaceId(), 'all')
  const task = resolveTask(snapshot.tasks, taskId)
  if (!task.cancelable || !ACTIVE.has(task.status)) {
    throw new Error(`Task ${task.id} cannot be cancelled now (${task.status}).`)
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
  return queueResult(
    `I asked to cancel “${cancelled.title || task.title}” (${cancelled.id}); Activity shows status ${cancelled.status}.`,
    cancelled.id,
  )
}

export async function resumeCanonicalQueueTask(taskId: string, confirm: boolean): Promise<CommandResult> {
  if (!confirm) throw new Error('Resuming requires confirm=true after an explicit user request.')
  const snapshot = await fetchCanonicalTasks(workspaceId(), 'all')
  const task = resolveTask(snapshot.tasks, taskId)
  if (!canResumeCanonicalTask(task)) {
    throw new Error(`Task ${task.id} cannot be resumed now (${task.status}).`)
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
  return queueResult(
    `I resumed “${resumed.title || task.title}” (${resumed.id}); its current status is ${resumed.status}.`,
    resumed.id,
  )
}

export async function retryCanonicalQueueTask(taskId: string, confirm: boolean): Promise<CommandResult> {
  if (!confirm) throw new Error('Retrying requires confirm=true after an explicit user request.')
  const snapshot = await fetchCanonicalTasks(workspaceId(), 'all')
  const task = resolveRetryTask(snapshot.tasks, taskId)
  const retried = await retryCanonicalTask(task.id, workspaceId())
  return queueResult(
    `I retried “${retried.title || task.title}” (${retried.id}); Activity shows status ${retried.status}.`,
    retried.id,
  )
}
