/**
 * HTTP adapter for typed generation.video.
 *
 * Posts the closed envelope to /api/v1/generation/commands. It does not read
 * useStore or applicationAdapters; Studio button wiring remains pending.
 */
import { BASE } from '../../api/http'
import {
  buildVideoGenerationCommand,
  effectiveVideoRequestsMatch,
  mcpArgumentsFromCommand,
  videoGenerationPresentation,
  VIDEO_GENERATION_OPERATION,
  type AgentGenerationVideoAction,
  type VideoGenerationCommand,
  type VideoGenerationPresentation,
} from './videoGenerationCapability'
import type { GenerationSubmissionContext } from '../studio/generationProvenance'

export interface VideoGenerationReceipt {
  version: 1
  commandId: string
  operation: typeof VIDEO_GENERATION_OPERATION
  status: 'queued'
  taskIds: string[]
  result: {
    job_id: string
    task_id: string
    workspace: string
    status: 'queued'
  }
  commandVersion?: 2
  fingerprintVersion?: 2
  contentFingerprint?: string
}

export interface VideoGenerationSubmitResult {
  receipt: VideoGenerationReceipt
  replayed: boolean
  command: VideoGenerationCommand
  presentation: VideoGenerationPresentation
  mcpArguments: Record<string, unknown>
  message: string
  taskId: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) return fallback
  const detail = payload.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (isRecord(detail) && typeof detail.message === 'string' && detail.message.trim()) {
    return detail.message
  }
  return fallback
}

async function readJson(response: Response): Promise<unknown> {
  return response.json().catch(() => undefined)
}

function receiptRecord(value: unknown): Record<string, unknown> | null {
  if (!isRecord(value)) return null
  if ('receipt' in value && isRecord(value.receipt)) return value.receipt
  return value
}

function asReceipt(value: unknown, command: VideoGenerationCommand): VideoGenerationReceipt {
  const receipt = receiptRecord(value)
  if (!receipt
    || receipt.operation !== VIDEO_GENERATION_OPERATION
    || receipt.commandId !== command.intent_id
    || !isRecord(receipt.result)
    || receipt.result.workspace !== command.input.workspace) {
    throw new Error(
      isRecord(value)
        ? 'generation.video receipt does not match the submitted command'
        : 'generation.video receipt is missing',
    )
  }
  return receipt as unknown as VideoGenerationReceipt
}

function wizardHeaders(context?: GenerationSubmissionContext): Record<string, string> {
  const headers: Record<string, string> = {
    'content-type': 'application/json',
    'X-Hocus-UI-Surface': 'wizard',
  }
  if (!context?.workflowId && !context?.runId) return headers
  headers['X-Hocus-UI-Context'] = JSON.stringify({
    ...(context.workflowId ? { workflowId: context.workflowId } : {}),
    ...(context.runId ? { runId: context.runId } : {}),
  })
  return headers
}

function queuedMessage(replayed: boolean, presentation: VideoGenerationPresentation): string {
  if (replayed) return `Reused generation.video admission in ${presentation.workspace}`
  return `Queued generation.video in ${presentation.workspace} with ${presentation.modelType} ${presentation.resolution} ${presentation.videoLength} frames`
}

export function createVideoGenerationAdapter(options: { fetch?: typeof fetch } = {}) {
  const send = options.fetch ?? globalThis.fetch.bind(globalThis)

  return {
    buildCommand: buildVideoGenerationCommand,
    presentation: videoGenerationPresentation,
    mcpArguments: mcpArgumentsFromCommand,
    matchesMcp(command: VideoGenerationCommand, mcpArguments: Record<string, unknown>) {
      return effectiveVideoRequestsMatch(command, mcpArguments)
    },
    async submit(
      action: AgentGenerationVideoAction,
      context?: GenerationSubmissionContext,
    ): Promise<VideoGenerationSubmitResult> {
      const command = buildVideoGenerationCommand(action)
      const presentation = videoGenerationPresentation(action)
      const response = await send(`${BASE}/api/v1/generation/commands`, {
        method: 'POST',
        headers: wizardHeaders(context),
        body: JSON.stringify(command),
      })
      const payload = await readJson(response)
      if (!response.ok) {
        throw new Error(errorMessage(payload, `generation.video failed (${response.status})`))
      }
      const receipt = asReceipt(payload, command)
      const replayed = isRecord(payload) && payload.replayed === true
      return {
        receipt,
        replayed,
        command,
        presentation,
        mcpArguments: mcpArgumentsFromCommand(command),
        message: queuedMessage(replayed, presentation),
        taskId: receipt.result.task_id,
      }
    },
    async recover(workspace: string, intentId: string): Promise<VideoGenerationReceipt> {
      const params = new URLSearchParams({ workspace, intent_id: intentId })
      const response = await send(`${BASE}/api/v1/generation/commands/receipt?${params}`)
      const payload = await readJson(response)
      if (!response.ok) {
        throw new Error(errorMessage(payload, `generation.video receipt failed (${response.status})`))
      }
      return asReceipt(payload, {
        version: 2,
        operation: VIDEO_GENERATION_OPERATION,
        intent_id: intentId,
        input: { workspace, params: {} },
      })
    },
  }
}

export type VideoGenerationAdapter = ReturnType<typeof createVideoGenerationAdapter>
