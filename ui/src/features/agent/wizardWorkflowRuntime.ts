import {
  fetchWizardWorkflows,
  saveWizardWorkflows,
  type WizardWorkflowCollectionPayload,
} from '../../api/client'
import type { CanonicalTaskEvent } from '../../lib/canonicalTaskEvents'
import { cardFromReport, type WizardExecutionCard } from './executionCards'
import { executionKey, executionReport } from './agentContract'

export type WizardWorkflowState =
  | 'prepared' | 'queued' | 'waiting' | 'running' | 'completed'
  | 'awaiting_input' | 'partial' | 'failed' | 'retrying' | 'cancelled'

export type WizardWorkflowStepState =
  | 'pending' | 'running' | 'waiting' | 'awaiting_input'
  | 'completed' | 'failed' | 'cancelled'

export interface WizardWorkflowInputOption {
  value: unknown
  label: string
  description?: string
  field?: string
}

/**
 * The durable, user-facing decision checkpoint for a workflow step.
 *
 * `answer` stays null while this is an active question. Once answered, the
 * same record is retained as an audit checkpoint (with `answeredAt`) while
 * the workflow re-runs the exact same step. Keeping the request and answer
 * together makes reloads and duplicate UI events deterministic.
 */
export interface WizardWorkflowPendingInput {
  workflowId: string
  stepId: string
  reason: string
  fields: string[]
  options: WizardWorkflowInputOption[]
  recommended: unknown
  resolvedEntityIds: Record<string, string>
  answer: Record<string, unknown> | null
  version: number
  requestedAt: number
  createdAt: number
  updatedAt: number
  answeredAt: number
}

/** Input request returned by a step before it can continue. */
export interface WizardWorkflowInputRequest {
  reason: string
  fields: string[]
  options?: WizardWorkflowInputOption[]
  recommended?: unknown
  resolvedEntityIds?: Record<string, string>
  version?: number
}

export interface WizardWorkflowAnswerOptions {
  version?: number
  stepId?: string
}

export interface WizardWorkflowStepRecord {
  stepId: string
  kind: string
  state: WizardWorkflowStepState
  input: Record<string, unknown>
  output: Record<string, unknown>
  taskId: string
  pipelineId: string
  outputRefs: string[]
  executionKey: string
  startedAt: number
  completedAt: number
  attempts: number
  error: string
}

export interface WizardWorkflowRecord {
  workflowId: string
  type: string
  workspace: string
  userRequest: string
  state: WizardWorkflowState
  currentStep: number
  steps: WizardWorkflowStepRecord[]
  resolvedEntityIds: Record<string, string>
  inputSnapshot: Record<string, unknown>
  taskIds: string[]
  pipelineIds: string[]
  outputRefs: string[]
  confirmationScope: string[]
  processedEventIds: number[]
  attempts: number
  createdAt: number
  updatedAt: number
  recoverableError: string
  cancelRequested: boolean
  resumeRequested: boolean
  pendingInput: WizardWorkflowPendingInput | null
}

export interface WizardWorkflowCollection {
  version: 1
  revision: number
  workflows: WizardWorkflowRecord[]
}

export interface WizardWorkflowPersistence {
  load(workspace: string): Promise<WizardWorkflowCollection>
  save(workspace: string, collection: WizardWorkflowCollection): Promise<WizardWorkflowCollection>
}

export interface WizardWorkflowStepResult {
  state: 'completed' | 'queued' | 'waiting' | 'running' | 'awaiting_input'
  output?: Record<string, unknown>
  taskId?: string
  pipelineId?: string
  outputRefs?: string[]
  resolvedEntityIds?: Record<string, string>
  awaitingInput?: WizardWorkflowInputRequest
  /** Alias accepted while callers migrate to `awaitingInput`. */
  inputRequest?: WizardWorkflowInputRequest
}

export interface WizardWorkflowStepContext {
  workflow: Readonly<WizardWorkflowRecord>
  step: Readonly<WizardWorkflowStepRecord>
  inputSnapshot: Readonly<Record<string, unknown>>
}

export interface WizardWorkflowStepDefinition {
  stepId: string
  kind: string
  execute(context: WizardWorkflowStepContext): Promise<WizardWorkflowStepResult>
}

export interface WizardWorkflowDefinition {
  type: string
  steps: WizardWorkflowStepDefinition[]
}

export interface StartWizardWorkflowInput {
  workflowId?: string
  type: string
  workspace: string
  userRequest: string
  inputSnapshot?: Record<string, unknown>
  stepInputs?: Record<string, Record<string, unknown>>
  confirmationScope?: string[]
}

export interface WizardWorkflowUpdate {
  workflow: WizardWorkflowRecord
  card: WizardExecutionCard
}

const WORKFLOW_STATES = new Set<WizardWorkflowState>([
  'prepared', 'queued', 'waiting', 'running', 'completed',
  'awaiting_input', 'partial', 'failed', 'retrying', 'cancelled',
])
const STEP_STATES = new Set<WizardWorkflowStepState>([
  'pending', 'running', 'waiting', 'awaiting_input', 'completed', 'failed', 'cancelled',
])
const TERMINAL_TASK_STATES = new Set(['completed', 'failed', 'cancelled', 'interrupted'])
const ACTIVE_TASK_STATES = new Set(['created', 'queued', 'waiting_resource', 'running'])

function clone<T>(value: T): T {
  if (typeof structuredClone === 'function') return structuredClone(value)
  return JSON.parse(JSON.stringify(value)) as T
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : []
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))]
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

const UNSAFE_FIELD_SEGMENTS = new Set(['__proto__', 'prototype', 'constructor'])

/**
 * Field paths are part of a persisted checkpoint and can therefore come from
 * an older client or a manually edited payload. Keep the dot-path convenience
 * while rejecting paths that could mutate an object's prototype when the
 * answer is applied.
 */
function normalizeFieldPath(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const segments = value.split('.').map(item => item.trim())
  if (!segments.length || segments.some(segment => !segment || UNSAFE_FIELD_SEGMENTS.has(segment))) return null
  return segments.join('.')
}

function normalizeInputOption(value: unknown): WizardWorkflowInputOption | null {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return { value, label: String(value) }
  }
  if (!isRecord(value)) return null
  const optionValue = Object.prototype.hasOwnProperty.call(value, 'value')
    ? value.value
    : Object.prototype.hasOwnProperty.call(value, 'id') ? value.id : value.key
  if (optionValue === undefined || optionValue === null) return null
  const label = typeof value.label === 'string' && value.label.trim()
    ? value.label
    : String(optionValue)
  const option: WizardWorkflowInputOption = { value: clone(optionValue), label }
  if (typeof value.description === 'string' && value.description.trim()) option.description = value.description
  if (typeof value.field === 'string' && value.field.trim()) option.field = value.field
  return option
}

function normalizeInputRequest(value: unknown): WizardWorkflowInputRequest | null {
  if (!isRecord(value)) return null
  if (!Array.isArray(value.fields) || !value.fields.length || !value.fields.every(field => typeof field === 'string')) {
    return null
  }
  const normalizedFields = value.fields.map(normalizeFieldPath)
  if (normalizedFields.some(field => !field)) return null
  const fields = unique(normalizedFields as string[])
  if (!fields.length) return null
  const options = Array.isArray(value.options)
    ? value.options.map(normalizeInputOption).filter((item): item is WizardWorkflowInputOption => Boolean(item))
    : []
  const request: WizardWorkflowInputRequest = {
    reason: String(value.reason || '').trim(),
    fields,
    options,
    recommended: Object.prototype.hasOwnProperty.call(value, 'recommended')
      ? clone(value.recommended) : null,
    resolvedEntityIds: isRecord(value.resolvedEntityIds)
      ? clone(value.resolvedEntityIds) as Record<string, string> : {},
  }
  const version = Number(value.version)
  if (Number.isFinite(version) && version > 0) request.version = Math.max(1, Math.floor(version))
  return request
}

function normalizePendingInput(
  value: unknown,
  workflowId: string,
  fallbackStepId: string,
): WizardWorkflowPendingInput | null {
  if (!isRecord(value)) return null
  const request = normalizeInputRequest(value)
  if (!request) return null
  const stepId = String(value.stepId || fallbackStepId).trim()
  if (!stepId) return null
  const createdAt = Math.max(0, Number(value.createdAt) || Number(value.requestedAt) || 0)
  const requestedAt = Math.max(0, Number(value.requestedAt) || createdAt)
  const updatedAt = Math.max(0, Number(value.updatedAt) || requestedAt)
  const answeredAt = Math.max(0, Number(value.answeredAt) || 0)
  const version = Math.max(1, Math.floor(Number(value.version) || request.version || 1))
  const answer = isRecord(value.answer) ? clone(value.answer) : null
  return {
    workflowId,
    stepId,
    reason: request.reason,
    fields: request.fields,
    options: request.options || [],
    recommended: clone(request.recommended),
    resolvedEntityIds: clone(request.resolvedEntityIds || {}),
    answer,
    version,
    requestedAt,
    createdAt,
    updatedAt,
    answeredAt,
  }
}

function sameValue(left: unknown, right: unknown): boolean {
  if (Object.is(left, right)) return true
  try { return JSON.stringify(left) === JSON.stringify(right) } catch { return false }
}

function applyDeclaredFields(
  base: Record<string, unknown>,
  fields: string[],
  answer: Record<string, unknown>,
): Record<string, unknown> {
  const result = clone(base)
  for (const field of fields) {
    if (!Object.prototype.hasOwnProperty.call(answer, field)) continue
    const segments = field.split('.').map(item => item.trim()).filter(Boolean)
    if (!segments.length || segments.some(segment => UNSAFE_FIELD_SEGMENTS.has(segment))) continue
    let target = result
    for (const segment of segments.slice(0, -1)) {
      if (!isRecord(target[segment])) target[segment] = {}
      target = target[segment] as Record<string, unknown>
    }
    target[segments.at(-1) as string] = clone(answer[field])
  }
  return result
}

function validateInputAnswer(
  pending: WizardWorkflowPendingInput,
  answer: Record<string, unknown>,
): void {
  const declared = new Set(pending.fields)
  const supplied = Object.keys(answer)
  const extra = supplied.filter(field => !declared.has(field))
  if (extra.length) throw new Error(`Input answer contains undeclared field(s): ${extra.join(', ')}`)
  const missing = pending.fields.filter(field => !Object.prototype.hasOwnProperty.call(answer, field))
  if (missing.length) throw new Error(`Input answer is missing field(s): ${missing.join(', ')}`)
  for (const field of pending.fields) {
    const value = answer[field]
    if (value === undefined || (typeof value === 'string' && !value.trim())) {
      throw new Error(`Input answer for ${field} must not be empty.`)
    }
    const options = pending.options.filter(option => !option.field || option.field === field)
    if (options.length && !options.some(option => sameValue(option.value, value))) {
      throw new Error(`Input answer for ${field} is not one of the available options.`)
    }
  }
}

function failureState(workflow: WizardWorkflowRecord): 'partial' | 'failed' {
  return workflow.steps.some(step => step.state === 'completed') ? 'partial' : 'failed'
}

function normalizeStep(value: unknown, index: number): WizardWorkflowStepRecord {
  const raw = value && typeof value === 'object' ? value as Record<string, unknown> : {}
  const state = STEP_STATES.has(raw.state as WizardWorkflowStepState)
    ? raw.state as WizardWorkflowStepState : 'pending'
  return {
    stepId: String(raw.stepId || `step-${index + 1}`),
    kind: String(raw.kind || ''),
    state,
    input: clone((raw.input && typeof raw.input === 'object' ? raw.input : {}) as Record<string, unknown>),
    output: clone((raw.output && typeof raw.output === 'object' ? raw.output : {}) as Record<string, unknown>),
    taskId: String(raw.taskId || ''),
    pipelineId: String(raw.pipelineId || ''),
    outputRefs: stringList(raw.outputRefs),
    executionKey: String(raw.executionKey || ''),
    startedAt: Math.max(0, Number(raw.startedAt) || 0),
    completedAt: Math.max(0, Number(raw.completedAt) || 0),
    attempts: Math.max(0, Number(raw.attempts) || 0),
    error: String(raw.error || ''),
  }
}

function normalizeWorkflow(value: unknown): WizardWorkflowRecord | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Record<string, unknown>
  const workflowId = String(raw.workflowId || '')
  const type = String(raw.type || '')
  const workspace = String(raw.workspace || '')
  if (!workflowId || !type || !workspace) return null
  const steps = Array.isArray(raw.steps) ? raw.steps.map(normalizeStep) : []
  const currentStep = Math.min(steps.length, Math.max(0, Number(raw.currentStep) || 0))
  const pendingInput = normalizePendingInput(
    raw.pendingInput,
    workflowId,
    steps[currentStep]?.stepId || '',
  )
  let state = WORKFLOW_STATES.has(raw.state as WizardWorkflowState)
    ? raw.state as WizardWorkflowState : 'prepared'
  // A short compatibility window lets a newer UI recover a checkpoint that
  // was written by an older backend which only knew the generic `waiting`
  // state. The pending request is the unambiguous discriminator.
  if (pendingInput?.answer === null
    && (state === 'waiting' || state === 'running' || state === 'prepared' || state === 'awaiting_input')) {
    state = 'awaiting_input'
    const activeStep = steps[currentStep]
    if (activeStep && (activeStep.state === 'waiting' || activeStep.state === 'running')) activeStep.state = 'awaiting_input'
  }
  return {
    workflowId, type, workspace,
    userRequest: String(raw.userRequest || ''),
    state,
    currentStep,
    steps,
    resolvedEntityIds: clone((raw.resolvedEntityIds && typeof raw.resolvedEntityIds === 'object'
      ? raw.resolvedEntityIds : {}) as Record<string, string>),
    inputSnapshot: clone((raw.inputSnapshot && typeof raw.inputSnapshot === 'object'
      ? raw.inputSnapshot : {}) as Record<string, unknown>),
    taskIds: stringList(raw.taskIds),
    pipelineIds: stringList(raw.pipelineIds),
    outputRefs: stringList(raw.outputRefs),
    confirmationScope: stringList(raw.confirmationScope),
    processedEventIds: Array.isArray(raw.processedEventIds)
      ? raw.processedEventIds.map(Number).filter(item => Number.isInteger(item) && item > 0).slice(-500)
      : [],
    attempts: Math.max(0, Number(raw.attempts) || 0),
    createdAt: Math.max(0, Number(raw.createdAt) || 0),
    updatedAt: Math.max(0, Number(raw.updatedAt) || 0),
    recoverableError: String(raw.recoverableError || ''),
    cancelRequested: raw.cancelRequested === true,
    resumeRequested: raw.resumeRequested === true,
    pendingInput,
  }
}

function normalizeCollection(value: WizardWorkflowCollectionPayload): WizardWorkflowCollection {
  const workflows = (Array.isArray(value.workflows) ? value.workflows : [])
    .map(normalizeWorkflow)
    .filter((item): item is WizardWorkflowRecord => Boolean(item))
  return { version: 1, revision: Math.max(0, Number(value.revision) || 0), workflows }
}

function mergeCollections(
  local: WizardWorkflowCollection,
  remote: WizardWorkflowCollection,
): WizardWorkflowCollection {
  const byId = new Map(remote.workflows.map(workflow => [workflow.workflowId, workflow]))
  for (const workflow of local.workflows) {
    const existing = byId.get(workflow.workflowId)
    if (!existing || workflow.updatedAt >= existing.updatedAt) byId.set(workflow.workflowId, workflow)
  }
  return { version: 1, revision: remote.revision, workflows: [...byId.values()].slice(-100) }
}

export const apiWizardWorkflowPersistence: WizardWorkflowPersistence = {
  async load(workspace) {
    return normalizeCollection(await fetchWizardWorkflows(workspace))
  },
  async save(workspace, collection) {
    const payload = await saveWizardWorkflows(workspace, collection)
    return normalizeCollection(payload)
  },
}

function workflowCard(workflow: WizardWorkflowRecord): WizardExecutionCard {
  const step = workflow.steps[workflow.currentStep] || workflow.steps.at(-1)
  const state = workflow.state === 'completed' ? 'completed'
    : workflow.state === 'partial' ? 'partial'
      : workflow.state === 'failed' || workflow.state === 'cancelled' ? 'failed'
        : workflow.state === 'awaiting_input' ? 'awaiting_input'
          : workflow.state === 'prepared' ? 'prepared'
            : workflow.state === 'queued' || workflow.state === 'waiting' ? 'queued'
              : 'running'
  let message = workflow.recoverableError
  if (!message && workflow.state === 'awaiting_input') {
    message = `Workflow “${workflow.type}” necesita información: ${workflow.pendingInput?.reason || 'falta una decisión.'}`
  } else if (!message && workflow.state === 'completed') {
    message = `Workflow “${workflow.type}” completado.`
  } else if (!message) {
    message = `Workflow “${workflow.type}”: ${step?.kind || workflow.state} (${workflow.currentStep + 1}/${workflow.steps.length}).`
  }
  return cardFromReport(executionReport({
    state,
    message,
    target: { kind: 'wizard_workflow', id: workflow.workflowId, title: workflow.type },
    taskId: step?.taskId || workflow.taskIds.at(-1),
    pipelineId: step?.pipelineId || workflow.pipelineIds.at(-1),
    outputNames: workflow.outputRefs,
    recoverable: workflow.state === 'failed' || workflow.state === 'partial',
    executionKey: executionKey({
      workspace: workflow.workspace,
      type: workflow.type,
      targetId: workflow.workflowId,
      params: workflow.inputSnapshot,
    }),
  }), workflow.workflowId)
}

export class WizardWorkflowRuntime {
  private collection: WizardWorkflowCollection = { version: 1, revision: 0, workflows: [] }
  private workspace = ''
  private definitions = new Map<string, WizardWorkflowDefinition>()
  private listeners = new Set<(update: WizardWorkflowUpdate) => void>()
  private locks = new Map<string, Promise<void>>()
  private persistence: WizardWorkflowPersistence
  private opened = false
  private pendingEvents: CanonicalTaskEvent[] = []
  private openSequence = 0

  constructor(persistence: WizardWorkflowPersistence = apiWizardWorkflowPersistence) {
    this.persistence = persistence
  }

  register(definition: WizardWorkflowDefinition): void {
    if (!definition.type || !definition.steps.length) throw new Error('A workflow definition needs a type and steps.')
    if (this.definitions.has(definition.type)) throw new Error(`Workflow ${definition.type} is already registered.`)
    const ids = definition.steps.map(step => step.stepId)
    if (new Set(ids).size !== ids.length) throw new Error(`Workflow ${definition.type} has duplicate step ids.`)
    this.definitions.set(definition.type, definition)
    if (this.opened) {
      for (const workflow of this.collection.workflows) {
        if (workflow.type !== definition.type || workflow.workspace !== this.workspace) continue
        const step = workflow.steps[workflow.currentStep]
        if (workflow.state === 'prepared' || workflow.state === 'retrying'
          || (workflow.state === 'running' && step?.state !== 'waiting' && step?.state !== 'awaiting_input')) {
          void this.advance(workflow.workflowId).catch(() => undefined)
        }
      }
    }
  }

  subscribe(listener: (update: WizardWorkflowUpdate) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  list(): WizardWorkflowRecord[] { return clone(this.collection.workflows) }

  get(workflowId: string): WizardWorkflowRecord | undefined {
    const workflow = this.collection.workflows.find(item => item.workflowId === workflowId)
    return workflow ? clone(workflow) : undefined
  }

  async open(workspace: string): Promise<WizardWorkflowRecord[]> {
    const sequence = ++this.openSequence
    const targetWorkspace = workspace || 'default'
    this.opened = false
    this.workspace = targetWorkspace
    const loaded = await this.persistence.load(targetWorkspace)
    if (sequence !== this.openSequence || this.workspace !== targetWorkspace) return this.list()
    this.collection = loaded
    this.opened = true
    for (const workflow of this.collection.workflows) {
      if (workflow.workspace === this.workspace) this.emit(workflow)
    }
    const pending = this.pendingEvents.splice(0)
    for (const event of pending) await this.handleTaskEvent(event)
    return this.list()
  }

  async start(input: StartWizardWorkflowInput): Promise<WizardWorkflowRecord> {
    if (input.workspace !== this.workspace) await this.open(input.workspace)
    const definition = this.definitions.get(input.type)
    if (!definition) throw new Error(`Workflow definition ${input.type} is not registered.`)
    const workflowId = input.workflowId || globalThis.crypto?.randomUUID?.()
      || `workflow-${Date.now()}-${Math.random().toString(36).slice(2)}`
    const existing = this.collection.workflows.find(item => item.workflowId === workflowId)
    if (existing) return clone(existing)
    const now = Date.now()
    const workflow: WizardWorkflowRecord = {
      workflowId, type: input.type, workspace: input.workspace,
      userRequest: input.userRequest,
      state: 'prepared', currentStep: 0,
      steps: definition.steps.map(step => ({
        stepId: step.stepId, kind: step.kind, state: 'pending',
        input: clone(input.stepInputs?.[step.stepId] || {}), output: {},
        taskId: '', pipelineId: '', outputRefs: [],
        executionKey: executionKey({
          workspace: input.workspace, type: `${input.type}:${step.stepId}`,
          targetId: workflowId, params: input.stepInputs?.[step.stepId] || {},
        }),
        startedAt: 0, completedAt: 0, attempts: 0, error: '',
      })),
      resolvedEntityIds: {}, inputSnapshot: clone(input.inputSnapshot || {}),
      taskIds: [], pipelineIds: [], outputRefs: [],
      confirmationScope: unique(input.confirmationScope || []),
      processedEventIds: [], attempts: 0, createdAt: now, updatedAt: now,
      recoverableError: '', cancelRequested: false, resumeRequested: false,
      pendingInput: null,
    }
    this.collection.workflows.push(workflow)
    await this.persist()
    this.emit(workflow)
    await this.advance(workflowId)
    return this.get(workflowId) as WizardWorkflowRecord
  }

  async handleTaskEvent(event: CanonicalTaskEvent): Promise<void> {
    if (!this.opened) {
      this.pendingEvents.push(clone(event))
      return
    }
    const matches = this.collection.workflows.filter(workflow => {
      const step = workflow.steps[workflow.currentStep]
      return workflow.workspace === this.workspace
        && step?.state === 'waiting'
        && step.taskId === event.task_id
        && !workflow.processedEventIds.includes(event.event_id)
    })
    await Promise.all(matches.map(workflow => this.serial(workflow.workflowId, async () => {
      const current = this.find(workflow.workflowId)
      const step = current.steps[current.currentStep]
      if (!step || step.state !== 'waiting' || step.taskId !== event.task_id) return
      if (current.processedEventIds.includes(event.event_id)) return
      const status = String(event.changes.status || '')
      if (!TERMINAL_TASK_STATES.has(status) && !ACTIVE_TASK_STATES.has(status)) return
      current.processedEventIds = [...current.processedEventIds, event.event_id].slice(-500)
      current.updatedAt = Date.now()
      if (ACTIVE_TASK_STATES.has(status)) {
        current.state = status === 'running' ? 'running'
          : status === 'waiting_resource' ? 'waiting' : 'queued'
        await this.persist()
        this.emit(current)
        return
      }
      if (status === 'completed') {
        step.state = 'completed'
        step.completedAt = current.updatedAt
        step.outputRefs = unique([...step.outputRefs, ...stringList(event.changes.result_refs)])
        step.output = { ...step.output, taskStatus: status, eventId: event.event_id }
        current.outputRefs = unique([...current.outputRefs, ...step.outputRefs])
        current.currentStep += 1
        current.state = current.currentStep >= current.steps.length ? 'completed' : 'running'
      } else {
        step.state = status === 'cancelled' ? 'cancelled' : 'failed'
        step.error = String((event.changes.error as Record<string, unknown> | undefined)?.message
          || event.changes.message || `Task ${event.task_id} ${status}`)
        current.state = status === 'cancelled' ? 'cancelled' : failureState(current)
        current.recoverableError = step.error
      }
      await this.persist()
      this.emit(current)
      if (status === 'completed' && current.state !== 'completed') await this.advanceUnlocked(current.workflowId)
    })))
  }

  async cancel(workflowId: string): Promise<WizardWorkflowRecord> {
    await this.serial(workflowId, async () => {
      const workflow = this.find(workflowId)
      workflow.cancelRequested = true
      workflow.resumeRequested = false
      workflow.state = 'cancelled'
      const step = workflow.steps[workflow.currentStep]
      if (step && step.state !== 'completed') step.state = 'cancelled'
      workflow.updatedAt = Date.now()
      await this.persist()
      this.emit(workflow)
    })
    return this.get(workflowId) as WizardWorkflowRecord
  }

  async answer(
    workflowId: string,
    answer: Record<string, unknown>,
    options?: number | WizardWorkflowAnswerOptions,
  ): Promise<WizardWorkflowRecord> {
    await this.serial(workflowId, async () => {
      const workflow = this.find(workflowId)
      const step = workflow.steps[workflow.currentStep]
      const pending = workflow.pendingInput
      // Answer delivery is idempotent. A duplicate click/replayed message
      // after the checkpoint was consumed must not execute the step twice.
      if (workflow.state !== 'awaiting_input' || step?.state !== 'awaiting_input' || !pending || pending.answer !== null) return
      if (pending.stepId !== step.stepId) throw new Error('The pending input belongs to a different workflow step.')
      const answerOptions = typeof options === 'number' ? { version: options } : options
      if (answerOptions?.stepId && answerOptions.stepId !== step.stepId) {
        throw new Error(`Input answer targets ${answerOptions.stepId}, not ${step.stepId}.`)
      }
      if (answerOptions?.version !== undefined && answerOptions.version !== pending.version) {
        throw new Error(`Input answer is stale (expected version ${pending.version}).`)
      }
      if (!isRecord(answer)) throw new Error('Input answer must be a JSON object.')
      validateInputAnswer(pending, answer)

      const now = Date.now()
      step.input = applyDeclaredFields(step.input, pending.fields, answer)
      workflow.inputSnapshot = applyDeclaredFields(workflow.inputSnapshot, pending.fields, answer)
      pending.answer = clone(answer)
      pending.answeredAt = now
      pending.updatedAt = now
      step.state = 'pending'
      step.error = ''
      step.taskId = ''
      step.pipelineId = ''
      step.completedAt = 0
      workflow.state = 'retrying'
      workflow.recoverableError = ''
      workflow.cancelRequested = false
      workflow.resumeRequested = true
      workflow.attempts += 1
      workflow.updatedAt = now
      await this.persistAndEmit(workflow)
      await this.advanceUnlocked(workflowId)
    })
    return this.get(workflowId) as WizardWorkflowRecord
  }

  async resume(
    workflowId: string,
    answer?: Record<string, unknown>,
    options?: number | WizardWorkflowAnswerOptions,
  ): Promise<WizardWorkflowRecord> {
    if (answer !== undefined) return this.answer(workflowId, answer, options)
    await this.serial(workflowId, async () => {
      const workflow = this.find(workflowId)
      if (workflow.state !== 'failed' && workflow.state !== 'cancelled' && workflow.state !== 'partial') return
      const previousState = workflow.state
      const step = workflow.steps[workflow.currentStep]
      if (step && step.state !== 'completed') {
        step.state = 'pending'
        step.error = ''
        step.taskId = ''
      }
      workflow.state = 'retrying'
      workflow.recoverableError = ''
      workflow.cancelRequested = false
      workflow.resumeRequested = true
      workflow.attempts += 1
      if (previousState === 'cancelled' && workflow.pendingInput?.answer === null) workflow.pendingInput = null
      workflow.updatedAt = Date.now()
      await this.persist()
      this.emit(workflow)
      await this.advanceUnlocked(workflowId)
    })
    return this.get(workflowId) as WizardWorkflowRecord
  }

  private async advance(workflowId: string): Promise<void> {
    await this.serial(workflowId, () => this.advanceUnlocked(workflowId))
  }

  private async advanceUnlocked(workflowId: string): Promise<void> {
    const workflow = this.find(workflowId)
    const definition = this.definitions.get(workflow.type)
    if (!definition) return
    while (workflow.currentStep < workflow.steps.length) {
      if (workflow.cancelRequested) return
      const step = workflow.steps[workflow.currentStep]
      const stepDefinition = definition.steps.find(item => item.stepId === step.stepId)
      if (!stepDefinition) {
        workflow.state = failureState(workflow)
        workflow.recoverableError = `Missing workflow step definition ${step.stepId}.`
        workflow.updatedAt = Date.now()
        await this.persistAndEmit(workflow)
        return
      }
      if (step.state === 'completed') {
        workflow.currentStep += 1
        continue
      }
      if (step.state === 'waiting' || step.state === 'awaiting_input') return
      if (step.state === 'running') {
        workflow.state = failureState(workflow)
        workflow.recoverableError = `Step ${step.stepId} was interrupted after it started; resume it explicitly.`
        step.state = 'failed'
        step.error = workflow.recoverableError
        workflow.updatedAt = Date.now()
        await this.persistAndEmit(workflow)
        return
      }
      const now = Date.now()
      step.state = 'running'
      step.startedAt = step.startedAt || now
      step.attempts += 1
      step.error = ''
      workflow.state = workflow.resumeRequested ? 'retrying' : 'running'
      workflow.updatedAt = now
      await this.persistAndEmit(workflow)
      let result: WizardWorkflowStepResult
      try {
        result = await stepDefinition.execute({
          workflow: clone(workflow), step: clone(step), inputSnapshot: clone(workflow.inputSnapshot),
        })
      } catch (error) {
        step.state = 'failed'
        step.error = error instanceof Error ? error.message : String(error)
        workflow.state = failureState(workflow)
        workflow.recoverableError = step.error
        workflow.updatedAt = Date.now()
        await this.persistAndEmit(workflow)
        return
      }
      step.output = clone(result.output || {})
      step.taskId = result.taskId || ''
      step.pipelineId = result.pipelineId || ''
      step.outputRefs = unique(result.outputRefs || [])
      workflow.resolvedEntityIds = { ...workflow.resolvedEntityIds, ...(result.resolvedEntityIds || {}) }
      workflow.taskIds = unique([...workflow.taskIds, step.taskId])
      workflow.pipelineIds = unique([...workflow.pipelineIds, step.pipelineId])
      workflow.outputRefs = unique([...workflow.outputRefs, ...step.outputRefs])
      workflow.updatedAt = Date.now()
      workflow.resumeRequested = false
      if (result.state === 'completed') {
        step.state = 'completed'
        step.completedAt = workflow.updatedAt
        workflow.currentStep += 1
        workflow.state = workflow.currentStep >= workflow.steps.length ? 'completed' : 'running'
        await this.persistAndEmit(workflow)
        continue
      }
      if (result.state === 'awaiting_input') {
        const request = normalizeInputRequest(result.awaitingInput || result.inputRequest)
        if (!request || !request.reason) {
          step.state = 'failed'
          step.error = `Step ${step.stepId} requested input without a reason and declared fields.`
          workflow.state = failureState(workflow)
          workflow.recoverableError = step.error
          await this.persistAndEmit(workflow)
          return
        }
        const previousPending = workflow.pendingInput
        const version = request.version || (
          previousPending && previousPending.answer !== null ? previousPending.version + 1 : previousPending?.version || 1
        )
        const resolvedEntityIds = {
          ...workflow.resolvedEntityIds,
          ...(result.resolvedEntityIds || {}),
          ...(request.resolvedEntityIds || {}),
        }
        workflow.resolvedEntityIds = resolvedEntityIds
        const now = workflow.updatedAt
        workflow.pendingInput = {
          workflowId: workflow.workflowId,
          stepId: step.stepId,
          reason: request.reason,
          fields: request.fields,
          options: request.options || [],
          recommended: clone(request.recommended),
          resolvedEntityIds: clone(resolvedEntityIds),
          answer: null,
          version: Math.max(1, Math.floor(version)),
          requestedAt: now,
          createdAt: now,
          updatedAt: now,
          answeredAt: 0,
        }
        step.state = 'awaiting_input'
        workflow.state = 'awaiting_input'
        await this.persistAndEmit(workflow)
        return
      }
      if (!step.taskId) {
        step.state = 'failed'
        step.error = `Step ${step.stepId} returned ${result.state} without a canonical task id.`
        workflow.state = failureState(workflow)
        workflow.recoverableError = step.error
        await this.persistAndEmit(workflow)
        return
      }
      step.state = 'waiting'
      workflow.state = result.state === 'queued' ? 'queued' : 'waiting'
      await this.persistAndEmit(workflow)
      return
    }
    workflow.state = 'completed'
    workflow.updatedAt = Date.now()
    await this.persistAndEmit(workflow)
  }

  private find(workflowId: string): WizardWorkflowRecord {
    const workflow = this.collection.workflows.find(item => item.workflowId === workflowId)
    if (!workflow) throw new Error(`Workflow ${workflowId} does not exist.`)
    return workflow
  }

  private async persistAndEmit(workflow: WizardWorkflowRecord): Promise<void> {
    await this.persist()
    this.emit(this.find(workflow.workflowId))
  }

  private async persist(): Promise<void> {
    let candidate = clone(this.collection)
    let lastError: unknown
    // Workflow updates can race with conversation/library autosaves in another
    // tab. Re-read and merge a few times before surfacing a real persistence
    // failure; every retry still uses the server's current CAS revision.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      try {
        const saved = await this.persistence.save(this.workspace, clone(candidate))
        this.collection.revision = saved.revision
        return
      } catch (error) {
        lastError = error
        const remote = await this.persistence.load(this.workspace)
        candidate = mergeCollections(candidate, remote)
        this.collection = candidate
      }
    }
    throw lastError instanceof Error ? lastError : new Error('Could not persist Wizard workflow.')
  }

  private emit(workflow: WizardWorkflowRecord): void {
    const update = { workflow: clone(workflow), card: workflowCard(workflow) }
    for (const listener of this.listeners) listener(update)
  }

  private serial(workflowId: string, operation: () => Promise<void>): Promise<void> {
    const previous = this.locks.get(workflowId) || Promise.resolve()
    const next = previous.catch(() => undefined).then(operation)
    this.locks.set(workflowId, next)
    return next.finally(() => {
      if (this.locks.get(workflowId) === next) this.locks.delete(workflowId)
    })
  }
}

export const defaultWizardWorkflowRuntime = new WizardWorkflowRuntime()
