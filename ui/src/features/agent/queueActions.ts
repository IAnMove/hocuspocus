import { cancelCanonicalTask, fetchCanonicalTasks, resumeCanonicalTask, retryCanonicalTask, type CanonicalTask } from '../../api/client'
import { useStore } from '../../stores/useStore'
import { canResumeCanonicalTask } from '../../lib/canonicalTaskEvents'
import { openAgentActivityDetails } from './agentUiBus'

const ACTIVE = new Set(['created', 'queued', 'waiting_resource', 'running'])

function workspaceId(): string {
  return useStore.getState().activeWorkspace || 'default'
}

function formatTaskLine(task: CanonicalTask): string {
  const percent = Math.round(Math.max(0, Math.min(1, Number(task.progress || 0))) * 100)
  const waiting = task.status === 'waiting_resource'
    ? ` Esperando ${((task.resource_requirements || []).join(', ') || 'recurso')}.`
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
    if (!active.length) throw new Error('No hay ninguna tarea activa que seleccionar.')
    if (active.length > 1) {
      throw new Error(
        `Hay ${active.length} tareas activas; indica el id. `
        + active.slice(0, 8).map(task => `${task.id} (${task.title || task.kind})`).join('; '),
      )
    }
    return active[0]
  }
  const exact = tasks.find(task => task.id === needle)
  if (exact) return exact
  const exactBackend = tasks.filter(task => task.pipeline_id === needle || task.backend_job_id === needle)
  if (exactBackend.length === 1) return exactBackend[0]
  if (exactBackend.length > 1) throw new Error(`El identificador “${needle}” pertenece a varias tareas; usa el id canónico.`)
  const prefix = tasks.filter(task => task.id.startsWith(needle))
  if (prefix.length === 1) return prefix[0]
  throw new Error(`No encontré la tarea “${needle}” en la cola canónica.`)
}

function resolveRetryTask(tasks: CanonicalTask[], requestedId: string): CanonicalTask {
  const roots = tasks.filter(task => !task.parent_id && canResumeCanonicalTask(task))
  const needle = requestedId.trim()
  if (needle === 'latest') {
    const latest = [...roots].sort((left, right) => right.updated_at - left.updated_at)[0]
    if (!latest) throw new Error('No hay ninguna tarea fallida, cancelada o interrumpida que reintentar.')
    return latest
  }
  if (!needle) {
    if (!roots.length) throw new Error('No hay ninguna tarea reintentable.')
    if (roots.length > 1) {
      throw new Error(`Hay ${roots.length} tareas reintentables; indica el id o pide explícitamente “el último fallo”.`)
    }
    return roots[0]
  }
  const task = resolveTask(tasks, needle)
  if (!canResumeCanonicalTask(task)) {
    throw new Error(`La tarea ${task.id} no se puede reintentar ahora (${task.status}).`)
  }
  return task
}

export async function inspectCanonicalQueue(scope: 'active' | 'all'): Promise<string> {
  const result = await fetchCanonicalTasks(workspaceId(), scope === 'all' ? 'all' : 'active')
  const roots = result.tasks.filter(task => !task.parent_id)
  const active = roots.filter(task => ACTIVE.has(task.status))
  openAgentActivityDetails()
  if (!roots.length) {
    return scope === 'all'
      ? 'La cola canónica de este workspace está vacía. He abierto el historial de Activity.'
      : 'No hay tareas activas. He abierto Activity por si quieres ver el historial.'
  }
  const waiting = active.filter(task => task.status === 'waiting_resource')
  const gpuWait = waiting.filter(task =>
    (task.resource_requirements || []).some(resource => /gpu/i.test(resource))
    || (task.acquired_resources || []).some(resource => /gpu/i.test(resource))
    || /gpu/i.test(task.message || ''),
  )
  const lines = (scope === 'all' ? roots.slice(0, 12) : active).map(formatTaskLine)
  const waitNote = gpuWait.length
    ? ` La GPU está ocupada o pendiente: ${gpuWait.map(task => task.title || task.id).join(', ')}.`
    : waiting.length
      ? ` Hay ${waiting.length} tarea(s) esperando recurso.`
      : ''
  return `Cola ${scope}: ${active.length} activa(s) de ${roots.length} visibles.${waitNote} He abierto Activity.\n${lines.join('\n')}`
}

export async function cancelCanonicalQueueTask(taskId: string, confirm: boolean): Promise<string> {
  if (!confirm) throw new Error('Cancelar requiere confirm=true tras una petición explícita del usuario.')
  const snapshot = await fetchCanonicalTasks(workspaceId(), 'all')
  const task = resolveTask(snapshot.tasks, taskId)
  if (!task.cancelable || !ACTIVE.has(task.status)) {
    throw new Error(`La tarea ${task.id} no se puede cancelar ahora (${task.status}).`)
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
  openAgentActivityDetails()
  return `He pedido cancelar “${cancelled.title || task.title}” (${cancelled.id}); Activity muestra el estado ${cancelled.status}.`
}

export async function resumeCanonicalQueueTask(taskId: string, confirm: boolean): Promise<string> {
  if (!confirm) throw new Error('Reanudar requiere confirm=true tras una petición explícita del usuario.')
  const snapshot = await fetchCanonicalTasks(workspaceId(), 'all')
  const task = resolveTask(snapshot.tasks, taskId)
  if (!canResumeCanonicalTask(task)) {
    throw new Error(`La tarea ${task.id} no es reanudable ahora (${task.status}).`)
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
  openAgentActivityDetails()
  return `He reanudado “${resumed.title || task.title}” (${resumed.id}); el estado actual es ${resumed.status}.`
}

export async function retryCanonicalQueueTask(taskId: string, confirm: boolean): Promise<string> {
  if (!confirm) throw new Error('Reintentar requiere confirm=true tras una petición explícita del usuario.')
  const snapshot = await fetchCanonicalTasks(workspaceId(), 'all')
  const task = resolveRetryTask(snapshot.tasks, taskId)
  const retried = await retryCanonicalTask(task.id, workspaceId())
  openAgentActivityDetails()
  return `He reintentado “${retried.title || task.title}” (${retried.id}); Activity muestra el estado ${retried.status}.`
}
