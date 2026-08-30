export type AgentActionRisk = 'read' | 'edit' | 'compute' | 'external_cost'

export type AgentExecutionState =
  | 'prepared'
  | 'queued'
  | 'running'
  | 'completed'
  | 'partial'
  | 'failed'

export interface AgentExecutionTarget {
  kind: string
  id: string
  title: string
}

export interface AgentExecutionReport {
  state: AgentExecutionState
  message: string
  target?: AgentExecutionTarget
  taskId?: string
  pipelineId?: string
  outputNames?: string[]
  recoverable: boolean
  executionKey?: string
}

export interface AgentActionDefinitionMeta {
  type: string
  risk: AgentActionRisk
}

const COMPOUND_DEPENDENCIES: Record<string, readonly string[]> = {
  generate_comic: ['create_comic'],
  start_director_production: ['stage_story_video', 'stage_story_music_video'],
}

const EXPENSIVE_ACTIONS = new Set([
  'start_generation',
  'queue_sfx_pack',
  'generate_comic',
  'generate_comic_panel',
  'start_director_production',
  'generate_story_visuals',
  'render_series_shots',
  'assemble_series_episode',
  'export_3d_scene',
])

const QUEUED_ACTIONS = new Set(['start_generation', 'queue_sfx_pack', 'render_series_shots'])
const RUNNING_ACTIONS = new Set(['start_director_production', 'export_3d_scene', 'generate_story_visuals'])
const REUSABLE_STATES = new Set<AgentExecutionState>(['prepared', 'queued', 'running', 'completed'])

const recentExecutions = new Map<string, AgentExecutionReport>()

export function requiredPredecessor(actionType: string): string | undefined {
  const leaders = COMPOUND_DEPENDENCIES[actionType]
  return leaders?.join('|')
}

export function isExpensiveAction(actionType: string): boolean {
  return EXPENSIVE_ACTIONS.has(actionType)
}

export function inferExecutionState(actionType: string, ok: boolean): AgentExecutionState {
  if (!ok) return 'failed'
  if (QUEUED_ACTIONS.has(actionType)) return 'queued'
  if (RUNNING_ACTIONS.has(actionType)) return 'running'
  return 'completed'
}

export function stableSerialize(value: unknown): string {
  if (value == null || typeof value !== 'object') return JSON.stringify(value ?? null)
  if (Array.isArray(value)) return `[${value.map(item => stableSerialize(item)).join(',')}]`
  const entries = Object.entries(value as Record<string, unknown>)
    .filter(([, item]) => item !== undefined)
    .sort(([left], [right]) => left.localeCompare(right))
  return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableSerialize(item)}`).join(',')}}`
}

export function executionKey(input: {
  workspace: string
  type: string
  targetId?: string
  params?: unknown
}): string {
  return [
    (input.workspace || 'default').trim().toLowerCase(),
    input.type.trim(),
    (input.targetId || '').trim(),
    stableSerialize(input.params ?? {}),
  ].join('|')
}

export function executionReport(input: Partial<AgentExecutionReport> & Pick<AgentExecutionReport, 'state' | 'message'>): AgentExecutionReport {
  return {
    state: input.state,
    message: input.message,
    target: input.target,
    taskId: input.taskId,
    pipelineId: input.pipelineId,
    outputNames: input.outputNames,
    recoverable: input.recoverable === true,
    executionKey: input.executionKey,
  }
}

export function rememberExecution(report: AgentExecutionReport): void {
  if (report.executionKey) recentExecutions.set(report.executionKey, report)
}

export function reuseExecution(key: string): AgentExecutionReport | undefined {
  const existing = recentExecutions.get(key)
  if (!existing || !REUSABLE_STATES.has(existing.state)) return undefined
  return existing
}

export function clearExecutionMemory(): void {
  recentExecutions.clear()
}

export function bindGenerateComicTarget(
  createdProjectId: string | undefined,
  currentProjectId: string,
  currentTitle: string,
): string {
  if (createdProjectId && createdProjectId !== currentProjectId) {
    throw new Error(
      `No dibujo un cómic anterior: generate_comic debe usar el proyecto recién creado (${createdProjectId}), no “${currentTitle}”.`,
    )
  }
  return createdProjectId || currentProjectId
}

export function bindDirectorProductionTarget(
  stagedProductionId: string | undefined,
  currentProductionId: string,
  currentTitle: string,
): string {
  if (stagedProductionId && stagedProductionId !== currentProductionId) {
    throw new Error(
      `No inicio una producción anterior: start_director_production debe usar la producción recién preparada (${stagedProductionId}), no “${currentTitle}”.`,
    )
  }
  return stagedProductionId || currentProductionId
}

export function orderCompoundActions<T extends { type: string }>(actions: T[]): T[] {
  const ordered = actions.slice()
  for (const [follower, leaders] of Object.entries(COMPOUND_DEPENDENCIES)) {
    const followerIdx = ordered.findIndex(item => item.type === follower)
    const leaderIdx = ordered.findIndex(item => leaders.includes(item.type))
    if (followerIdx >= 0 && leaderIdx >= 0 && followerIdx < leaderIdx) {
      const [item] = ordered.splice(followerIdx, 1)
      const leaderNow = ordered.findIndex(entry => leaders.includes(entry.type))
      ordered.splice(leaderNow + 1, 0, item)
    }
  }
  return ordered
}
