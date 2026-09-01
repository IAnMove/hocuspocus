import type {
  AgentAction,
  AgentCancelTaskAction,
  AgentCreateWorkspaceAction,
  AgentInspectQueueAction,
  AgentOpenSeriesSectionAction,
  AgentOpenStorySectionAction,
  AgentResumeTaskAction,
  AgentRetryTaskAction,
  AgentSelectWorkspaceAction,
} from './agentActions'
import type {
  CapabilityDefinition,
  CapabilityExecutionOutcome,
} from './capabilityRegistry'
import type { AgentSeriesSection, AgentStorySection } from './agentUiBus'
import {
  openAgentSeriesSection,
  openAgentStorySection,
} from './agentUiBus'

/**
 * The registry owns the concrete implementation of defineCapability. Keeping
 * this module dependency-injected means it can be loaded after the core
 * registry definitions without creating an ESM initialization cycle.
 */
export type NavigationQueueCapabilityRegistrar = <TAction extends AgentAction>(
  definition: CapabilityDefinition<TAction>,
) => CapabilityDefinition<TAction>

const STORY_SECTIONS: readonly AgentStorySection[] = [
  'overview', 'assets', 'world', 'characters', 'relationships', 'structure',
  'music', 'trailer', 'productions', 'assembly',
]
const SERIES_SECTIONS: readonly AgentSeriesSection[] = [
  'setup', 'canon', 'episode', 'shots', 'review',
]
const storySectionSet = new Set<string>(STORY_SECTIONS)
const seriesSectionSet = new Set<string>(SERIES_SECTIONS)
const registeredRegistrars = new WeakSet<NavigationQueueCapabilityRegistrar>()

const ACTIVITY_TARGET = {
  kind: 'activity',
  id: 'activity',
  title: 'Activity',
} as const

function text(value: unknown, maxLength: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
}

function storySection(raw: Record<string, unknown>): AgentOpenStorySectionAction | null {
  const section = text(raw.story_section, 40)
  return storySectionSet.has(section)
    ? { type: 'open_story_section', section: section as AgentStorySection }
    : null
}

function seriesSection(raw: Record<string, unknown>): AgentOpenSeriesSectionAction | null {
  const section = text(raw.series_section, 40)
  return seriesSectionSet.has(section)
    ? { type: 'open_series_section', section: section as AgentSeriesSection }
    : null
}

function queueScope(raw: Record<string, unknown>): AgentInspectQueueAction {
  return {
    type: 'inspect_queue',
    scope: text(raw.queue_scope, 12) === 'all' ? 'all' : 'active',
  }
}

function queueMutation<TAction extends AgentCancelTaskAction | AgentResumeTaskAction | AgentRetryTaskAction>(
  type: TAction['type'],
  raw: Record<string, unknown>,
): TAction | null {
  if (raw.confirm !== true) return null
  return {
    type,
    taskId: text(raw.task_id, 160),
    confirm: true,
  } as TAction
}

function workspaceName<TAction extends AgentSelectWorkspaceAction | AgentCreateWorkspaceAction>(
  type: TAction['type'],
  raw: Record<string, unknown>,
): TAction | null {
  const name = text(raw.workspace_name, 120)
  return name ? { type, workspaceName: name } as TAction : null
}

function navigationOutcome(
  outcome: CapabilityExecutionOutcome,
  message: string,
): CapabilityExecutionOutcome {
  return { ...outcome, message }
}

/**
 * Register navigation, queue and workspace actions that used to be handled
 * by the large legacy action switch. Calling this more than once with the
 * same registry function is deliberately a no-op, which makes hot reload and
 * test setup safe.
 */
export function registerNavigationQueueCapabilities(
  register: NavigationQueueCapabilityRegistrar,
): void {
  if (registeredRegistrars.has(register)) return

  register<AgentOpenStorySectionAction>({
    name: 'open_story_section',
    title: 'Open a Story Lab section',
    description: 'Open one exact Story Lab section and make the selection visible in the real lab UI.',
    useWhen: 'The user asks for a specific part of Story Lab or that section helps explain the next step.',
    parameters: ['story_section'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'open_story_section' },
        story_section: { type: 'string', enum: STORY_SECTIONS },
      },
      required: ['type', 'story_section'],
    },
    risk: 'read',
    confirmation: 'none',
    progress: 'Abriendo una sección de Story Lab…',
    resolve: storySection,
    validate(action) {
      return storySectionSet.has(action.section) ? [] : ['story_section must identify a Story Lab section']
    },
    async prepare(action) { return action },
    async execute(action, context) {
      const outcome = await context.adapters.storyLab.open()
      openAgentStorySection(action.section)
      return navigationOutcome(outcome, `He abierto Story Lab → ${action.section}.`)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'application_section', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'story_lab', anchors: ['section'], replay: 'atomic' },
  })

  register<AgentOpenSeriesSectionAction>({
    name: 'open_series_section',
    title: 'Open a Series Lab section',
    description: 'Open one exact Series Lab section and make the selection visible in the real lab UI.',
    useWhen: 'The user asks for a specific part of Series Lab or that section helps explain the next step.',
    parameters: ['series_section'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'open_series_section' },
        series_section: { type: 'string', enum: SERIES_SECTIONS },
      },
      required: ['type', 'series_section'],
    },
    risk: 'read',
    confirmation: 'none',
    progress: 'Abriendo una sección de Series Lab…',
    resolve: seriesSection,
    validate(action) {
      return seriesSectionSet.has(action.section) ? [] : ['series_section must identify a Series Lab section']
    },
    async prepare(action) { return action },
    async execute(action, context) {
      const outcome = await context.adapters.seriesLab.open()
      openAgentSeriesSection(action.section)
      return navigationOutcome(outcome, `He abierto Series Lab → ${action.section}.`)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'application_section', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'series_lab', anchors: ['section'], replay: 'atomic' },
  })

  register<AgentInspectQueueAction>({
    name: 'inspect_queue',
    title: 'Inspect the canonical queue',
    description: 'Refresh the real task list and open Activity so the user sees current jobs.',
    useWhen: 'The user asks what is in the queue, why the GPU is waiting, or the status of a job.',
    parameters: ['queue_scope'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'inspect_queue' },
        queue_scope: { type: 'string', enum: ['', 'active', 'all'] },
      },
      required: ['type'],
    },
    risk: 'read',
    confirmation: 'none',
    progress: 'Consultando la cola canónica…',
    resolve: queueScope,
    validate(action) {
      return action.scope === 'active' || action.scope === 'all' ? [] : ['queue scope is invalid']
    },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.queue.inspect(action.scope)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'activity', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'action', anchors: ['activity'], replay: 'atomic' },
  })

  register<AgentCancelTaskAction>({
    name: 'cancel_task',
    title: 'Cancel a canonical task',
    description: 'Cancel one identified active task through the canonical API after an explicit user request.',
    useWhen: 'The user clearly asks to cancel the active job or a specific task id.',
    parameters: ['task_id', 'confirm'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'cancel_task' },
        task_id: { type: 'string', maxLength: 160 },
        confirm: { const: true },
      },
      required: ['type', 'confirm'],
    },
    risk: 'edit',
    confirmation: 'required',
    progress: 'Cancelando la tarea en la cola…',
    resolve(raw) { return queueMutation('cancel_task', raw) },
    validate(action) { return action.confirm === true ? [] : ['confirmation is required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      // Preserve the special Comic Director batch cancellation bridge from
      // the legacy action runner before touching the canonical task API.
      const { requestComicArtworkCancel } = await import('../comics/generateArtwork')
      const cancelledBatch = requestComicArtworkCancel()
      try {
        const outcome = await context.adapters.queue.cancel(action.taskId, action.confirm)
        return {
          ...outcome,
          message: cancelledBatch
            ? `${outcome.message} También he pedido cancelar el lote de viñetas; las terminadas se conservan.`
            : outcome.message,
        }
      } catch (error) {
        if (!cancelledBatch) throw error
        return {
          message: 'He pedido cancelar el lote de viñetas; las ilustraciones terminadas se conservan.',
          target: ACTIVITY_TARGET,
        }
      }
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'activity', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'action', anchors: ['activity'], replay: 'atomic' },
  })

  register<AgentResumeTaskAction>({
    name: 'resume_task',
    title: 'Resume a canonical task',
    description: 'Resume one identified resumable task through the canonical API after an explicit user request.',
    useWhen: 'The user clearly asks to resume a specific interrupted or failed resumable task.',
    parameters: ['task_id', 'confirm'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'resume_task' },
        task_id: { type: 'string', maxLength: 160 },
        confirm: { const: true },
      },
      required: ['type', 'confirm'],
    },
    risk: 'edit',
    confirmation: 'required',
    progress: 'Reanudando la tarea en la cola…',
    resolve(raw) { return queueMutation('resume_task', raw) },
    validate(action) { return action.confirm === true ? [] : ['confirmation is required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.queue.resume(action.taskId, action.confirm)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'activity', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'action', anchors: ['activity'], replay: 'atomic' },
  })

  register<AgentRetryTaskAction>({
    name: 'retry_task',
    title: 'Retry a canonical task',
    description: 'Retry a persisted failed, cancelled or interrupted task through the canonical retry endpoint and show Activity.',
    useWhen: 'The user explicitly asks to retry a specific task or the latest failure.',
    parameters: ['task_id', 'confirm'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'retry_task' },
        task_id: { type: 'string', maxLength: 160 },
        confirm: { const: true },
      },
      required: ['type', 'confirm'],
    },
    risk: 'compute',
    confirmation: 'required',
    progress: 'Reintentando la tarea en la cola…',
    resolve(raw) { return queueMutation('retry_task', raw) },
    validate(action) { return action.confirm === true ? [] : ['confirmation is required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.queue.retry(action.taskId, action.confirm)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'activity', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'action', anchors: ['activity'], replay: 'atomic' },
  })

  register<AgentSelectWorkspaceAction>({
    name: 'select_workspace',
    title: 'Select a workspace',
    description: 'Resolve an existing workspace by exact name, switch the canonical backend/store context, and keep the Wizard turn visible.',
    useWhen: 'The user asks to work in an existing named workspace.',
    parameters: ['workspace_name'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'select_workspace' },
        workspace_name: { type: 'string', maxLength: 120 },
      },
      required: ['type', 'workspace_name'],
    },
    risk: 'edit',
    confirmation: 'none',
    progress: 'Cambiando de workspace…',
    resolve(raw) { return workspaceName('select_workspace', raw) },
    validate(action) { return action.workspaceName.trim() ? [] : ['workspace name is required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.workspace.select(action)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'workspace', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'action', anchors: ['workspace'], replay: 'atomic' },
  })

  register<AgentCreateWorkspaceAction>({
    name: 'create_workspace',
    title: 'Create and select a workspace',
    description: 'Create a new isolated workspace through the canonical API, select it, and continue the Wizard conversation there.',
    useWhen: 'The user explicitly asks to create a new named workspace.',
    parameters: ['workspace_name'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'create_workspace' },
        workspace_name: { type: 'string', maxLength: 120 },
      },
      required: ['type', 'workspace_name'],
    },
    risk: 'edit',
    confirmation: 'none',
    progress: 'Creando el workspace…',
    resolve(raw) { return workspaceName('create_workspace', raw) },
    validate(action) { return action.workspaceName.trim() ? [] : ['workspace name is required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.workspace.create(action)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'workspace', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'action', anchors: ['workspace'], replay: 'atomic' },
  })

  registeredRegistrars.add(register)
}
