import type { AgentAction, AgentActionResult } from './agentActions'
import {
  executionKey,
  executionReport,
  type AgentExecutionReport,
} from './agentContract'
import {
  getCapability,
  parseRegisteredCapability,
  type CapabilityExecutionContext,
} from './capabilityRegistry'
import {
  createCommandEnvelope,
  normalizeCommandResult,
  presentationPlanFromCapabilityPresentation,
  type ArtifactKind,
  type CommandResultStatus,
  type EntityRef,
} from './commandContract'
import { replayWizardPresentation } from './wizardPresentation'

export type CapabilityRunnerStage =
  | 'resolve'
  | 'validate'
  | 'prepare'
  | 'confirm'
  | 'execute'
  | 'correlate'
  | 'track'
  | 'report'

export interface CapabilityRunnerOptions extends CapabilityExecutionContext {
  workspace: string
  onStage?: (stage: CapabilityRunnerStage, actionType: string) => void
}

function stage(
  options: CapabilityRunnerOptions,
  current: CapabilityRunnerStage,
  actionType: string,
): void {
  options.onStage?.(current, actionType)
}

function requireConfirmation(action: AgentAction, required: boolean): void {
  if (!required) return
  if (!('confirm' in action) || action.confirm !== true) {
    throw new Error(`${action.type} requiere confirmación explícita.`)
  }
}

function commandId(): string {
  return globalThis.crypto?.randomUUID?.()
    || `command-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

function resultStatus(report: AgentExecutionReport): CommandResultStatus {
  if (report.state === 'failed') return 'failed'
  if (report.state === 'partial') return 'partial'
  if (report.state === 'queued' || report.state === 'running') return 'queued'
  return 'completed'
}

function artifactKind(name: string): ArtifactKind {
  if (/\.(png|jpe?g|webp|gif|avif)$/i.test(name)) return 'image'
  if (/\.(wav|mp3|flac|ogg|m4a|aac)$/i.test(name)) return 'audio'
  if (/\.(mp4|webm|mov|mkv)$/i.test(name)) return 'video'
  if (/\.(scene\.json|glb|gltf)$/i.test(name)) return 'scene'
  return 'document'
}

export async function runRegisteredCapability(
  action: AgentAction,
  options: CapabilityRunnerOptions,
): Promise<AgentActionResult | undefined> {
  const definition = getCapability(action.type)
  if (!definition) return undefined

  stage(options, 'resolve', action.type)
  stage(options, 'validate', action.type)
  const errors = definition.validate(action)
  if (errors.length) throw new Error(errors.join('; '))

  stage(options, 'prepare', action.type)
  const prepared = await definition.prepare(action, options)

  stage(options, 'confirm', action.type)
  requireConfirmation(prepared, definition.confirmation === 'required')

  const executionCommandId = commandId()

  stage(options, 'execute', action.type)
  const executed = await definition.execute(prepared, options)

  stage(options, 'correlate', action.type)
  const target = definition.correlate(prepared, executed)
  if (executed.target && !target) {
    throw new Error(`${action.type} ejecutó una navegación que no pudo correlacionarse.`)
  }
  const entity: EntityRef | undefined = target?.id ? {
    kind: target.kind || 'entity',
    id: target.id,
    workspaceId: options.workspace || 'default',
  } : undefined
  const envelope = createCommandEnvelope({
    commandId: executionCommandId,
    capability: prepared.type,
    workspaceId: options.workspace || 'default',
    actor: 'wizard',
    target: entity,
    input: prepared,
    presentation: presentationPlanFromCapabilityPresentation(definition.presentation),
  })

  if (prepared.type === 'prepare_video') {
    await replayWizardPresentation(envelope.presentation)
  }

  stage(options, 'track', action.type)
  const tracked = await definition.track(prepared, executed, options)

  stage(options, 'report', action.type)
  const message = definition.summarize(prepared, tracked)
  const report: AgentExecutionReport = tracked.report || executionReport({
    state: definition.report.successState,
    message,
    target,
    taskId: tracked.taskId,
    pipelineId: tracked.pipelineId,
    outputNames: tracked.outputNames,
    assetIds: tracked.assetIds,
    recoverable: false,
    executionKey: executionKey({
      workspace: options.workspace || 'default',
      type: prepared.type,
      targetId: target?.id,
      params: prepared,
    }),
  })
  const outputNames = [...new Set([...(report.outputNames || []), ...(report.assetIds || [])].filter(Boolean))]
  const commandResult = normalizeCommandResult({
    commandId: envelope.commandId,
    status: resultStatus(report),
    entities: entity ? [entity] : [],
    artifacts: entity ? outputNames.map(name => ({
      id: name,
      kind: artifactKind(name),
      owner: entity,
      taskId: report.taskId,
      uri: name,
      metadata: {},
    })) : [],
    taskIds: report.taskId ? [report.taskId] : [],
    pipelineIds: report.pipelineId ? [report.pipelineId] : [],
    navigationTarget: definition.presentation.destination === 'action' ? undefined : {
      destination: definition.presentation.destination,
      entity,
      anchor: definition.presentation.anchors[0],
    },
  }, envelope.workspaceId)
  return { action: prepared, ok: true, message, report, command: envelope, commandResult }
}

export async function resolveAndRunRegisteredCapability(
  name: string,
  raw: Record<string, unknown>,
  options: CapabilityRunnerOptions,
): Promise<AgentActionResult | undefined> {
  const definition = getCapability(name)
  if (!definition) return undefined
  stage(options, 'resolve', name)
  const action = parseRegisteredCapability(name, raw)
  if (!action) throw new Error(`${name} no cumple el contrato de entrada.`)
  return runRegisteredCapability(action, {
    ...options,
    onStage: (current, actionType) => {
      if (current !== 'resolve') options.onStage?.(current, actionType)
    },
  })
}
