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
  | 'partial' | 'failed' | 'retrying' | 'cancelled'

export type WizardWorkflowStepState =
  | 'pending' | 'running' | 'waiting' | 'completed' | 'failed' | 'cancelled'

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
  state: 'completed' | 'queued' | 'waiting' | 'running'
  output?: Record<string, unknown>
  taskId?: string
  pipelineId?: string
  outputRefs?: string[]
  resolvedEntityIds?: Record<string, string>
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
  'partial', 'failed', 'retrying', 'cancelled',
])
const STEP_STATES = new Set<WizardWorkflowStepState>([
  'pending', 'running', 'waiting', 'completed', 'failed', 'cancelled',
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
  return {
    workflowId, type, workspace,
    userRequest: String(raw.userRequest || ''),
    state: WORKFLOW_STATES.has(raw.state as WizardWorkflowState)
      ? raw.state as WizardWorkflowState : 'prepared',
    currentStep: Math.min(steps.length, Math.max(0, Number(raw.currentStep) || 0)),
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
        : workflow.state === 'prepared' ? 'prepared'
          : workflow.state === 'queued' || workflow.state === 'waiting' ? 'queued'
            : 'running'
  const message = workflow.recoverableError
    || (workflow.state === 'completed'
      ? `Workflow “${workflow.type}” completado.`
      : `Workflow “${workflow.type}”: ${step?.kind || workflow.state} (${workflow.currentStep + 1}/${workflow.steps.length}).`)
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
          || (workflow.state === 'running' && step?.state !== 'waiting')) {
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

  async resume(workflowId: string): Promise<WizardWorkflowRecord> {
    await this.serial(workflowId, async () => {
      const workflow = this.find(workflowId)
      if (workflow.state !== 'failed' && workflow.state !== 'cancelled' && workflow.state !== 'partial') return
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
      if (step.state === 'waiting') return
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
    this.emit(workflow)
  }

  private async persist(): Promise<void> {
    try {
      const saved = await this.persistence.save(this.workspace, clone(this.collection))
      this.collection.revision = saved.revision
    } catch {
      const remote = await this.persistence.load(this.workspace)
      const merged = mergeCollections(this.collection, remote)
      const saved = await this.persistence.save(this.workspace, clone(merged))
      merged.revision = saved.revision
      this.collection = merged
    }
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
