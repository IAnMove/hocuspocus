export const LIVE_TASK_STATUSES = new Set(['created', 'queued', 'waiting_resource', 'running'])
export const FAILED_TASK_STATUSES = new Set(['failed', 'interrupted', 'cancelled'])

export type ActivityReadingState =
  | 'prepared'
  | 'admitted'
  | 'running'
  | 'failed'
  | 'partial'
  | 'completed'

export interface ActivityTaskLike {
  id: string
  root_id: string
  parent_id?: string | null
  kind?: string
  title?: string
  workflow?: string
  status: string
  phase?: string
  message?: string
  detail?: string
  current?: number
  total?: number
  progress?: number
  created_at: number
  queued_at?: number | null
  started_at?: number | null
  updated_at: number
  completed_at?: number | null
  attempt?: number
  max_attempts?: number
  backend_job_id?: string
  pipeline_id?: string
  result_refs?: string[]
  error?: { message?: string; retryable?: boolean } | null
  metadata?: Record<string, unknown>
  workspace?: string
  resumable?: boolean
  recoverable?: boolean
  cancelable?: boolean
  provider?: string
  model?: string
  resource_requirements?: string[]
  acquired_resources?: string[]
  server_origin?: string
  token_usage?: { prompt?: number; completion?: number; total?: number; calls?: number }
}

export interface ActivityAttempt {
  id: string
  taskId: string
  attempt: number
  readingState: ActivityReadingState
  status: string
  message: string
  error: string
  resultRefs: string[]
  createdAt: number
  updatedAt: number
}

export interface ActivityJob {
  id: string
  title: string
  readingState: ActivityReadingState
  task: ActivityTaskLike
  attempts: ActivityAttempt[]
}

export interface ActivityProjectTarget {
  kind: string
  id: string
  title: string
}

export interface ActivityGroup {
  id: string
  intentId: string
  receiptId: string
  rootId: string
  workspace: string
  title: string
  readingState: ActivityReadingState
  progress: number
  hasArtifact: boolean
  createdAt: number
  primary: ActivityTaskLike
  jobs: ActivityJob[]
  artifacts: string[]
  previousAttempt?: ActivityAttempt
  recoveryReason: string
  project?: ActivityProjectTarget
}

export interface ActivityFocusRequest {
  taskId?: string
  intentId?: string
  receiptId?: string
  inspectPreviousAttempt?: boolean
}

export interface ActivityChrome {
  selectedId: string | null
  expandedIds: readonly string[]
  inspectedAttemptByGroup: Readonly<Record<string, string>>
}

const ARTIFACT_KIND = /generat|image|video|audio|render|export|speech|music|sfx|tool|model/

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function text(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function metadataOf(task: ActivityTaskLike): Record<string, unknown> {
  return isRecord(task.metadata) ? task.metadata : {}
}

export function taskIntentId(task: ActivityTaskLike): string {
  const metadata = metadataOf(task)
  const receipt = isRecord(metadata.receipt) ? metadata.receipt : {}
  const command = isRecord(metadata.command) ? metadata.command : {}
  return text(metadata.intent_id)
    || text(metadata.intentId)
    || text(metadata.command_id)
    || text(metadata.commandId)
    || text(receipt.commandId)
    || text(receipt.intent_id)
    || text(command.command_id)
    || text(command.commandId)
}

export function taskReceiptId(task: ActivityTaskLike): string {
  const metadata = metadataOf(task)
  const receipt = isRecord(metadata.receipt) ? metadata.receipt : {}
  return text(metadata.receipt_id)
    || text(metadata.receiptId)
    || text(receipt.commandId)
    || taskIntentId(task)
}

export function taskWorkspace(task: ActivityTaskLike): string {
  const metadata = metadataOf(task)
  return text(task.workspace) || text(metadata.workspace) || text(metadata.workspace_id)
}

export function taskArtifactRefs(task: ActivityTaskLike): string[] {
  const metadata = metadataOf(task)
  const fromTask = Array.isArray(task.result_refs)
    ? task.result_refs.filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
    : []
  const extra = [metadata.artifact_ids, metadata.output_files, metadata.outputNames]
    .flatMap(value => Array.isArray(value) ? value : [])
    .filter((item): item is string => typeof item === 'string' && Boolean(item.trim()))
  return [...new Set([...fromTask, ...extra])]
}

export function taskExpectsArtifact(task: ActivityTaskLike): boolean {
  const metadata = metadataOf(task)
  if (metadata.expects_artifact === false || metadata.expectsArtifact === false) return false
  if (metadata.expects_artifact === true || metadata.expectsArtifact === true) return true
  const kind = `${task.kind || ''} ${task.workflow || ''}`.toLowerCase()
  return ARTIFACT_KIND.test(kind)
}

export function isLiveStatus(status: string): boolean {
  return LIVE_TASK_STATUSES.has(status)
}

export function taskHasArtifact(task: ActivityTaskLike): boolean {
  return taskArtifactRefs(task).length > 0
}

export function taskReadingState(task: ActivityTaskLike): ActivityReadingState {
  if (FAILED_TASK_STATUSES.has(task.status)) return 'failed'
  if (task.status === 'running' || task.status === 'waiting_resource') return 'running'
  if (task.status === 'queued') return 'admitted'
  if (task.status === 'created') {
    return task.backend_job_id || taskIntentId(task) ? 'admitted' : 'prepared'
  }
  if (task.status === 'completed') {
    if (taskExpectsArtifact(task) && !taskHasArtifact(task)) return 'partial'
    return 'completed'
  }
  return 'admitted'
}

export function taskProgressPercent(task: ActivityTaskLike): number {
  const total = Number(task.total || 0)
  const current = Number(task.current || 0)
  if (total > 0) return Math.max(0, Math.min(100, (current / total) * 100))
  return Math.max(0, Math.min(100, Number(task.progress || 0) * 100))
}

function uniqueTasks(tasks: ActivityTaskLike[]): ActivityTaskLike[] {
  const byId = new Map<string, ActivityTaskLike>()
  for (const task of tasks) byId.set(task.id, task)
  return [...byId.values()]
}

function rootOf(task: ActivityTaskLike, byId: Map<string, ActivityTaskLike>): ActivityTaskLike {
  const seen = new Set<string>()
  let cursor = task
  while (cursor.parent_id && byId.has(cursor.parent_id) && !seen.has(cursor.id)) {
    seen.add(cursor.id)
    cursor = byId.get(cursor.parent_id) as ActivityTaskLike
  }
  return byId.get(cursor.root_id) || cursor
}

export function activityRequestKey(task: ActivityTaskLike, byId: Map<string, ActivityTaskLike>): string {
  const root = rootOf(task, byId)
  const intent = taskIntentId(root) || taskIntentId(task)
  if (intent) return `intent:${intent}`
  return `root:${root.root_id || root.id}`
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    const next = text(value)
    if (next) return next
  }
  return ''
}

function finiteNumber(value: unknown, fallback: number): number {
  const parsed = Number(value)
  if (Number.isFinite(parsed)) return parsed
  return fallback
}

const READING_STATES = new Set<string>(['prepared', 'admitted', 'running', 'failed', 'partial', 'completed'])

function asReadingState(value: string): ActivityReadingState | undefined {
  if (READING_STATES.has(value)) return value as ActivityReadingState
  return undefined
}

function failedDetail(task: ActivityTaskLike): string {
  if (!FAILED_TASK_STATUSES.has(task.status)) return ''
  return firstText(task.detail, task.message)
}

function asAttempt(task: ActivityTaskLike, overrides: Partial<ActivityAttempt> = {}): ActivityAttempt {
  const attempt = finiteNumber(overrides.attempt, finiteNumber(task.attempt, 1))
  return {
    id: firstText(overrides.id, `${task.id}:${attempt}`),
    taskId: task.id,
    attempt,
    readingState: overrides.readingState ?? taskReadingState(task),
    status: firstText(overrides.status, task.status),
    message: firstText(overrides.message, task.message),
    error: firstText(overrides.error, task.error?.message, failedDetail(task)),
    resultRefs: overrides.resultRefs ?? taskArtifactRefs(task),
    createdAt: finiteNumber(overrides.createdAt, finiteNumber(task.created_at, 0)),
    updatedAt: finiteNumber(overrides.updatedAt, finiteNumber(task.updated_at, 0)),
  }
}

function historyItemRefs(item: Record<string, unknown>): string[] | undefined {
  if (!Array.isArray(item.result_refs)) return undefined
  return item.result_refs.filter((value): value is string => typeof value === 'string')
}

function historyItemAttempt(task: ActivityTaskLike, item: unknown, index: number): ActivityAttempt | null {
  if (!isRecord(item)) return null
  const attempt = finiteNumber(item.attempt, index + 1)
  const nestedError = isRecord(item.error) ? item.error.message : ''
  return asAttempt(task, {
    id: firstText(item.id, `${task.id}:history:${attempt}`),
    attempt,
    readingState: asReadingState(text(item.readingState)),
    status: firstText(item.status, task.status),
    message: text(item.message),
    error: firstText(item.error, nestedError),
    resultRefs: historyItemRefs(item),
    createdAt: finiteNumber(item.created_at, finiteNumber(item.createdAt, finiteNumber(task.created_at, 0))),
    updatedAt: finiteNumber(item.updated_at, finiteNumber(item.updatedAt, 0)),
  })
}

function historyAttempts(task: ActivityTaskLike): ActivityAttempt[] {
  const metadata = metadataOf(task)
  const raw = metadata.previous_attempts || metadata.attempt_history || metadata.attempts
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item, index) => {
    const attempt = historyItemAttempt(task, item, index)
    return attempt ? [attempt] : []
  })
}

function jobAttempts(tasks: ActivityTaskLike[]): ActivityAttempt[] {
  const attempts = tasks.flatMap(task => [...historyAttempts(task), asAttempt(task)])
  const byId = new Map<string, ActivityAttempt>()
  for (const attempt of attempts) byId.set(attempt.id, attempt)
  return [...byId.values()].sort((left, right) => (
    left.attempt - right.attempt || left.createdAt - right.createdAt || left.id.localeCompare(right.id)
  ))
}

function allStatesAre(states: ActivityReadingState[], allowed: readonly ActivityReadingState[]): boolean {
  const permitted = new Set<string>(allowed)
  return states.every(state => permitted.has(state))
}

function isMixedPartial(states: ActivityReadingState[], missingExpectedArtifact: boolean): boolean {
  if (missingExpectedArtifact) return true
  if (states.includes('partial')) return true
  return states.includes('failed') && states.includes('completed')
}

function leftoverReading(states: ActivityReadingState[], hasArtifact: boolean): ActivityReadingState {
  if (states.includes('admitted')) return 'admitted'
  if (states.includes('prepared')) return 'prepared'
  if (states.includes('failed')) return 'failed'
  if (hasArtifact) return 'completed'
  return 'admitted'
}

function combineReadingState(
  states: ActivityReadingState[],
  hasArtifact: boolean,
  missingExpectedArtifact = false,
): ActivityReadingState {
  if (states.includes('running')) return 'running'
  if (allStatesAre(states, ['prepared'])) return 'prepared'
  if (allStatesAre(states, ['admitted', 'prepared']) && states.includes('admitted')) return 'admitted'
  if (allStatesAre(states, ['failed'])) return 'failed'
  if (allStatesAre(states, ['completed']) && !missingExpectedArtifact) return 'completed'
  if (isMixedPartial(states, missingExpectedArtifact)) return 'partial'
  return leftoverReading(states, hasArtifact)
}

function recoveryReason(tasks: ActivityTaskLike[], readingState: ActivityReadingState): string {
  const failed = [...tasks].reverse().find(task => FAILED_TASK_STATUSES.has(task.status) || task.error?.message)
  if (failed) return text(failed.error?.message) || failed.detail || failed.message || ''
  if (readingState === 'partial') {
    const incomplete = tasks.find(task => taskExpectsArtifact(task) && !taskHasArtifact(task))
    if (incomplete) return incomplete.detail || incomplete.message || ''
  }
  const waiting = tasks.find(task => task.status === 'waiting_resource')
  if (waiting) return waiting.detail || waiting.message || ''
  return ''
}

function projectTarget(task: ActivityTaskLike): ActivityProjectTarget | undefined {
  const metadata = metadataOf(task)
  const kind = text(metadata.entity_type) || text(metadata.project_kind) || text(metadata.target_kind)
  const id = text(metadata.project_id) || text(metadata.entity_id) || text(metadata.target_id)
  if (!kind || !id) return undefined
  return { kind, id, title: text(metadata.project_title) || text(metadata.entity_title) || id }
}

function byCreatedAsc(left: ActivityTaskLike, right: ActivityTaskLike): number {
  return finiteNumber(left.created_at, 0) - finiteNumber(right.created_at, 0) || left.id.localeCompare(right.id)
}

function latestTask(tasks: ActivityTaskLike[]): ActivityTaskLike {
  return [...tasks].sort((left, right) => (
    finiteNumber(right.attempt, 1) - finiteNumber(left.attempt, 1)
    || finiteNumber(right.created_at, 0) - finiteNumber(left.created_at, 0)
  ))[0]
}

function selectPrimary(ordered: ActivityTaskLike[]): ActivityTaskLike {
  const roots = ordered.filter(task => !task.parent_id)
  const liveMembers = ordered.filter(task => isLiveStatus(task.status))
  if (liveMembers[0]) return liveMembers[0]
  return latestTask(roots.length ? roots : ordered)
}

function missingExpectedArtifact(tasks: ActivityTaskLike[]): boolean {
  return tasks.some(task => task.status === 'completed' && taskExpectsArtifact(task) && !taskHasArtifact(task))
}

function jobBucketsFor(ordered: ActivityTaskLike[], primary: ActivityTaskLike): Map<string, ActivityTaskLike[]> {
  const buckets = new Map<string, ActivityTaskLike[]>()
  const children = ordered.filter(task => task.parent_id)
  const members = children.length ? children : ordered.filter(task => !task.parent_id)
  const source = members.length ? members : [primary]
  for (const task of source) {
    const list = buckets.get(task.id) ?? []
    list.push(task)
    buckets.set(task.id, list)
  }
  return buckets
}

function jobFromTasks(tasks: ActivityTaskLike[]): ActivityJob {
  const jobPrimary = [...tasks].sort((left, right) => (
    finiteNumber(right.attempt, 1) - finiteNumber(left.attempt, 1)
    || finiteNumber(right.updated_at, 0) - finiteNumber(left.updated_at, 0)
  ))[0]
  return {
    id: jobPrimary.id,
    title: firstText(jobPrimary.title, jobPrimary.kind, jobPrimary.id),
    readingState: combineReadingState(tasks.map(taskReadingState), tasks.some(taskHasArtifact), missingExpectedArtifact(tasks)),
    task: jobPrimary,
    attempts: jobAttempts(tasks),
  }
}

function previousFromAttempts(attempts: ActivityAttempt[]): ActivityAttempt | undefined {
  const currentAttempt = Math.max(1, ...attempts.map(item => item.attempt))
  const previous = [...attempts].reverse().find(item => item.attempt < currentAttempt)
  if (previous) return previous
  if (attempts.length > 1) return attempts[attempts.length - 2]
  return undefined
}

function buildGroup(id: string, members: ActivityTaskLike[]): ActivityGroup {
  const ordered = [...members].sort(byCreatedAsc)
  const roots = ordered.filter(task => !task.parent_id)
  const primary = selectPrimary(ordered)
  const jobs = [...jobBucketsFor(ordered, primary).values()].map(jobFromTasks).sort((left, right) => (
    byCreatedAsc(left.task, right.task)
  ))
  const artifacts = [...new Set(ordered.flatMap(taskArtifactRefs))]
  const readingState = combineReadingState(
    ordered.map(taskReadingState),
    artifacts.length > 0,
    missingExpectedArtifact(ordered),
  )
  const live = ordered.filter(task => isLiveStatus(task.status))
  return {
    id,
    intentId: firstText(taskIntentId(primary), taskIntentId(ordered[0])),
    receiptId: firstText(taskReceiptId(primary), taskReceiptId(ordered[0])),
    rootId: firstText(primary.root_id, primary.id),
    workspace: taskWorkspace(primary),
    title: firstText(primary.title, primary.kind, primary.id),
    readingState,
    progress: readingState === 'completed' ? 100 : taskProgressPercent(live[0] ?? primary),
    hasArtifact: artifacts.length > 0,
    createdAt: Math.min(...ordered.map(task => finiteNumber(task.created_at, 0))),
    primary,
    jobs,
    artifacts,
    previousAttempt: previousFromAttempts(jobAttempts(roots.length ? roots : ordered)),
    recoveryReason: recoveryReason(ordered, readingState),
    project: projectTarget(primary) ?? ordered.map(projectTarget).find(Boolean),
  }
}

export function groupActivityTasks(
  tasks: ActivityTaskLike[],
  options: { workspace?: string } = {},
): ActivityGroup[] {
  const scoped = uniqueTasks(tasks).filter(task => {
    if (!options.workspace) return true
    const workspace = taskWorkspace(task)
    return !workspace || workspace === options.workspace
  })
  const byId = new Map(scoped.map(task => [task.id, task]))
  const buckets = new Map<string, ActivityTaskLike[]>()
  for (const task of scoped) {
    const key = activityRequestKey(task, byId)
    const members = buckets.get(key) || []
    members.push(task)
    buckets.set(key, members)
  }
  const groups = [...buckets.entries()].map(([id, members]) => buildGroup(id, members))
  const live = groups.filter(group => group.readingState === 'prepared'
    || group.readingState === 'admitted'
    || group.readingState === 'running')
  const terminal = groups.filter(group => !live.includes(group))
  const byCreated = (left: ActivityGroup, right: ActivityGroup) => (
    right.createdAt - left.createdAt || left.id.localeCompare(right.id)
  )
  return [...live.sort(byCreated), ...terminal.sort(byCreated).slice(0, 12)]
}

export function findActivityGroup(
  groups: ActivityGroup[],
  request: ActivityFocusRequest,
): ActivityGroup | undefined {
  if (request.taskId) {
    const taskId = request.taskId
    const match = groups.find(group => (
      group.primary.id === taskId
      || group.rootId === taskId
      || group.jobs.some(job => job.id === taskId || job.attempts.some(attempt => attempt.taskId === taskId))
    ))
    if (match) return match
  }
  if (request.intentId) {
    const match = groups.find(group => group.intentId === request.intentId)
    if (match) return match
  }
  if (request.receiptId) {
    return groups.find(group => group.receiptId === request.receiptId)
  }
  return undefined
}

export function preserveActivityChrome(chrome: ActivityChrome): ActivityChrome {
  return {
    selectedId: chrome.selectedId,
    expandedIds: [...chrome.expandedIds],
    inspectedAttemptByGroup: { ...chrome.inspectedAttemptByGroup },
  }
}
