import i18n from '../../i18n'
import type { CapabilityDefinition, CapabilityExecutionContext, CapabilityExecutionOutcome, defineCapability } from './capabilityRegistry'
import {
  interpretLipsyncReply, lipsyncInput, lipsyncNote, postLipsyncRedo, type LipsyncEngine,
} from '../lipsync-redo/request'

export interface AgentLipsyncRedoAction {
  type: 'lipsync_redo'
  engine: LipsyncEngine
  confirm: true
  input: Record<string, unknown>
}

function engineOf(value: unknown): LipsyncEngine | null {
  return value === 'infinitetalk' ? value : null
}

function objectOf(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  return value as Record<string, unknown>
}

function wizardText(key: string, options?: Record<string, unknown>): string {
  const translate = i18n.t as (key: string, options?: Record<string, unknown>) => string
  return String(translate(`wizard:${key}`, options))
}

function guardedInput(action: AgentLipsyncRedoAction, workspace: string | undefined) {
  const named = typeof action.input.workspace === 'string' ? action.input.workspace : ''
  if (workspace && named && named !== workspace) {
    throw new Error(i18n.t('wizard:actionErrors.mediaMustSaveActiveWorkspace'))
  }
  return lipsyncInput(action.input, named || workspace || '', action.engine)
}

export async function executeLipsyncRedo(action: AgentLipsyncRedoAction, context: CapabilityExecutionContext): Promise<CapabilityExecutionOutcome> {
  const posted = await postLipsyncRedo(guardedInput(action, context.workspace), {
    surface: 'wizard', intentId: context.generationContext?.commandId,
  })
  const read = interpretLipsyncReply(posted.status, posted.body)
  if (read.kind === 'error') throw new Error(read.message || wizardText('replies.lipsFailed'))
  return {
    message: lipsyncNote(read, wizardText),
    metadata: posted.body && typeof posted.body === 'object' ? posted.body as Record<string, unknown> : {},
    outputNames: read.file ? [read.file] : [],
    target: { kind: 'output', id: read.file || action.engine, title: 'shot.lipsync.redo' },
  }
}

export function registerLipsyncRedoCapabilities(register: typeof defineCapability) {
  const definition: CapabilityDefinition<AgentLipsyncRedoAction> = {
    name: 'lipsync_redo',
    title: 'Redo the lips of a finished shot',
    description: 'Redo the lips of one finished shot as a new take. The original clip and any series approval stay. engine is infinitetalk (follow the source camera, Apache-2.0). longcat_avatar is a catalog model and is not a redo engine: it does not read the shot video. input names one target: production_id and shot, or series_id, episode_id and shot, or clip plus audio. Optional audio, source, span [start, end] seconds and offset. If the reply says the weights are missing, tell the user the disk size in bytes and call download_model with that model_type and confirm true. Do not put confirm_download in this action.',
    useWhen: 'The user asks to redo, fix or resync the lips or mouth of a finished video shot or clip, including an anime or stylized character.',
    parameters: ['engine', 'input', 'confirm'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'lipsync_redo' },
        confirm: { const: true },
        engine: { enum: ['infinitetalk'] },
        input: { type: 'object' },
      },
      required: ['type', 'confirm', 'engine', 'input'],
    },
    risk: 'compute', confirmation: 'required', progress: 'wizard:progress.lipsRedoing',
    resolve(raw) {
      const engine = engineOf(raw.engine)
      const input = objectOf(raw.input)
      if (raw.confirm !== true || !engine || !input) return null
      return { type: 'lipsync_redo', engine, confirm: true, input }
    },
    validate(action) {
      return action.confirm === true && engineOf(action.engine) ? [] : ['Confirm the lip redo and name infinitetalk.']
    },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.lipsyncRedo.command(action, context) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'output', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'videos', anchors: ['output'], replay: 'atomic' },
  }
  register(definition)
}
