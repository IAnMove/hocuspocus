export type GenerationActor = 'user' | 'wizard' | 'system' | 'unknown'

export interface GenerationSubmissionContext {
  actor: GenerationActor
  capability?: string
  commandId?: string
  workflowId?: string
  runId?: string
  workspaceCollectionId?: string
}

export function generationProvenancePayload(context?: GenerationSubmissionContext) {
  if (!context) return undefined
  const command = {
    ...(context.commandId ? { command_id: context.commandId } : {}),
    ...(context.workflowId ? { workflow_id: context.workflowId } : {}),
    ...(context.runId ? { run_id: context.runId } : {}),
  }
  return {
    actor: context.actor,
    tool: 'studio',
    ...(context.capability ? { capability: context.capability } : {}),
    ...(context.workspaceCollectionId ? { workspace_id: context.workspaceCollectionId } : {}),
    command,
  }
}

export function newUserGenerationContext(): GenerationSubmissionContext {
  return {
    actor: 'user',
    capability: 'start_generation',
    commandId: globalThis.crypto?.randomUUID?.()
      || `command-${Date.now()}-${Math.random().toString(36).slice(2)}`,
  }
}
