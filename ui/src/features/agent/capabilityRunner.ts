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

  stage(options, 'execute', action.type)
  const executed = await definition.execute(prepared, options)

  stage(options, 'correlate', action.type)
  const target = definition.correlate(prepared, executed)
  if (executed.target && !target) {
    throw new Error(`${action.type} ejecutó una navegación que no pudo correlacionarse.`)
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
  return { action: prepared, ok: true, message, report }
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
