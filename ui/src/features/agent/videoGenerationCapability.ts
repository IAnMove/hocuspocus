/**
 * Wizard capability for typed generation.video.
 *
 * This module is tested on its own. Store/applicationAdapters wiring is a
 * later integration; Wizard and MCP can still POST /api/v1/generation/commands.
 */
import { stableSerialize } from '../../lib/commandContract'
import { assertCanonicalAudioReference } from '../../lib/canonicalAudioReference'
import {
  VIDEO_GENERATION_OPERATION, VIDEO_GENERATION_SCHEMA_VERSION, VIDEO_MODEL_TYPES,
  WORKSPACE, MAX_PROMPT, MAX_INTENT, modelType, resolutionValue,
  detachedVideoGenerationCommand, type VideoGenerationCommand, type VideoModelType,
} from '../../lib/videoGenerationCommand'
export {
  VIDEO_GENERATION_OPERATION, VIDEO_GENERATION_SCHEMA_VERSION, VIDEO_MODEL_TYPES, VIDEO_MODEL_FAMILY,
  assertVideoGenerationCommand, detachedVideoGenerationCommand,
  type VideoGenerationCommand, type VideoModelType,
} from '../../lib/videoGenerationCommand'

export const VIDEO_GENERATION_DEFAULTS = {
  modelType: 't2v_1.3B' as const,
  resolution: '832x480',
  videoLength: 81,
  numInferenceSteps: 30,
  guidanceScale: 5,
  seed: -1,
  fps: 16,
}

export interface AgentGenerationVideoAction {
  type: 'generation_video'
  intentId: string
  workspace: string
  prompt: string
  modelType: VideoModelType
  resolution: string
  videoLength: number
  numInferenceSteps: number
  guidanceScale: number
  seed?: number
  negativePrompt?: string
  imageStart?: string | null
  workspaceCollectionId?: string
  confirm: true
}

export interface VideoGenerationPresentation {
  destination: 'studio'
  anchors: string[]
  workspace: string
  modelType: VideoModelType
  resolution: string
  videoLength: number
  prompt: string
  imageStart?: string | null
}

type OptionalField<T> = { ok: true, value?: T } | { ok: false }

interface ResolvedVideoFields {
  prompt: string
  workspace: string
  intent: string
  selectedModel: VideoModelType
  resolution: string
  videoLength: number
  steps: number
  guidance: number
}

export function alignWanT2vFrames(frames: number): number {
  const minimum = 5
  const step = 4
  const bounded = Math.max(minimum, Math.min(10_000, Math.round(frames)))
  const delta = (bounded - minimum) % step
  if (!delta) return bounded
  if (delta >= step / 2) {
    const raised = bounded + (step - delta)
    return raised > 10_000 ? bounded - delta : raised
  }
  const lowered = bounded - delta
  return lowered < minimum ? bounded + (step - delta) : lowered
}

export function framesFromDurationSeconds(seconds: number, fps = VIDEO_GENERATION_DEFAULTS.fps): number {
  return alignWanT2vFrames(seconds * fps)
}

function finiteNumber(value: unknown, minimum: number, maximum: number, integer = false): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  const bounded = Math.max(minimum, Math.min(maximum, value))
  return integer ? Math.round(bounded) : bounded
}

function literalPrompt(value: unknown): string | null {
  if (typeof value !== 'string' || value.length > MAX_PROMPT || !value.trim()) return null
  return value
}

function workspaceName(value: unknown): string | null {
  return typeof value === 'string' && WORKSPACE.test(value) ? value : null
}

function intentId(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' && value.length <= MAX_INTENT ? value : null
}

function defaultedModel(value: unknown): VideoModelType | null {
  return value === undefined ? VIDEO_GENERATION_DEFAULTS.modelType : modelType(value)
}

function defaultedResolution(value: unknown): string | null {
  return value === undefined ? VIDEO_GENERATION_DEFAULTS.resolution : resolutionValue(value)
}

function defaultedVideoLength(raw: Record<string, unknown>): number | undefined {
  if (raw.video_length !== undefined) return finiteNumber(raw.video_length, 5, 10_000, true)
  if (typeof raw.duration_seconds === 'number') return framesFromDurationSeconds(raw.duration_seconds)
  return VIDEO_GENERATION_DEFAULTS.videoLength
}

function defaultedSteps(value: unknown): number | undefined {
  if (value === undefined) return VIDEO_GENERATION_DEFAULTS.numInferenceSteps
  return finiteNumber(value, 1, 1000, true)
}

function defaultedGuidance(value: unknown): number | undefined {
  if (value === undefined) return VIDEO_GENERATION_DEFAULTS.guidanceScale
  return finiteNumber(value, 0, 1000)
}

function optionalImageStart(value: unknown): OptionalField<string | null> {
  if (value === undefined) return { ok: true }
  if (value === null || value === '') return { ok: true, value }
  if (typeof value !== 'string') return { ok: false }
  try {
    assertCanonicalAudioReference(value, 'image_start', 'video')
    return { ok: true, value }
  } catch {
    return { ok: false }
  }
}

function optionalCollectionId(value: unknown): OptionalField<string> {
  if (value === undefined || value === null) return { ok: true }
  if (typeof value === 'string' && value.trim() !== '' && value.length <= 200) {
    return { ok: true, value }
  }
  return { ok: false }
}

function optionalSeed(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isSafeInteger(value)) return value
  return undefined
}

function optionalNegativePrompt(value: unknown): string | undefined {
  if (typeof value === 'string' && value.length <= MAX_PROMPT) return value
  return undefined
}

function requiredResolvedFields(raw: Record<string, unknown>): ResolvedVideoFields | null {
  const prompt = literalPrompt(raw.prompt)
  const workspace = workspaceName(raw.workspace)
  const intent = intentId(raw.intent_id)
  const selectedModel = defaultedModel(raw.model_type)
  const resolution = defaultedResolution(raw.resolution)
  if (!prompt || !workspace || !intent || !selectedModel || !resolution) return null
  const videoLength = defaultedVideoLength(raw)
  const steps = defaultedSteps(raw.num_inference_steps)
  const guidance = defaultedGuidance(raw.guidance_scale)
  if (videoLength === undefined || steps === undefined || guidance === undefined) return null
  return { prompt, workspace, intent, selectedModel, resolution, videoLength, steps, guidance }
}

function videoActionFromResolved(
  fields: ResolvedVideoFields,
  extras: {
    seed?: number
    negativePrompt?: string
    imageStart?: string | null
    collectionId?: string
  },
): AgentGenerationVideoAction {
  const action: AgentGenerationVideoAction = {
    type: 'generation_video',
    intentId: fields.intent,
    workspace: fields.workspace,
    prompt: fields.prompt,
    modelType: fields.selectedModel,
    resolution: fields.resolution,
    videoLength: alignWanT2vFrames(fields.videoLength),
    numInferenceSteps: fields.steps,
    guidanceScale: fields.guidance,
    confirm: true,
  }
  if (extras.seed !== undefined) action.seed = extras.seed
  if (extras.negativePrompt !== undefined) action.negativePrompt = extras.negativePrompt
  if (extras.imageStart !== undefined) action.imageStart = extras.imageStart
  if (extras.collectionId !== undefined) action.workspaceCollectionId = extras.collectionId
  return action
}

export function resolveVideoGenerationAction(raw: Record<string, unknown>): AgentGenerationVideoAction | null {
  if (raw.confirm !== true) return null
  const fields = requiredResolvedFields(raw)
  const imageStart = optionalImageStart(raw.image_start)
  const collection = optionalCollectionId(raw.workspace_collection_id)
  if (!fields || !imageStart.ok || !collection.ok) return null
  return videoActionFromResolved(fields, {
    seed: optionalSeed(raw.seed),
    negativePrompt: optionalNegativePrompt(raw.negative_prompt),
    imageStart: imageStart.value,
    collectionId: collection.value,
  })
}

export function validateVideoGenerationAction(action: AgentGenerationVideoAction): string[] {
  if (action.confirm !== true) return ['confirmation is required']
  if (!action.prompt.trim()) return ['a literal prompt is required']
  if (!WORKSPACE.test(action.workspace)) return ['an explicit output workspace is required']
  if (!VIDEO_MODEL_TYPES.includes(action.modelType)) return ['choose t2v or t2v_1.3B']
  return []
}

export function videoGenerationPresentation(action: AgentGenerationVideoAction): VideoGenerationPresentation {
  const presentation: VideoGenerationPresentation = {
    destination: 'studio',
    anchors: ['video', 'generate', 'destination'],
    workspace: action.workspace,
    modelType: action.modelType,
    resolution: action.resolution,
    videoLength: action.videoLength,
    prompt: action.prompt,
  }
  if (action.imageStart !== undefined) presentation.imageStart = action.imageStart
  return presentation
}

function commandParamsFromAction(action: AgentGenerationVideoAction): Record<string, unknown> {
  const params: Record<string, unknown> = {
    prompt: action.prompt,
    model_type: action.modelType,
    resolution: action.resolution,
    video_length: action.videoLength,
    num_inference_steps: action.numInferenceSteps,
    guidance_scale: action.guidanceScale,
    generation_mode: 'video',
    image_mode: 0,
    multi_prompts_gen_type: 2,
  }
  if (action.seed !== undefined) params.seed = action.seed
  if (action.negativePrompt !== undefined) params.negative_prompt = action.negativePrompt
  if (action.imageStart !== undefined) params.image_start = action.imageStart
  return params
}

export function buildVideoGenerationCommand(action: AgentGenerationVideoAction): VideoGenerationCommand {
  const errors = validateVideoGenerationAction(action)
  if (errors.length) throw new Error(errors[0])
  const input: VideoGenerationCommand['input'] = {
    workspace: action.workspace,
    params: commandParamsFromAction(action),
  }
  if (action.workspaceCollectionId !== undefined) {
    input.workspace_collection_id = action.workspaceCollectionId
  }
  return detachedVideoGenerationCommand({
    version: VIDEO_GENERATION_SCHEMA_VERSION,
    operation: VIDEO_GENERATION_OPERATION,
    intent_id: action.intentId,
    input,
  })
}

export function mcpArgumentsFromCommand(command: VideoGenerationCommand): Record<string, unknown> {
  const arguments_ = { ...command } as Record<string, unknown>
  delete arguments_.operation
  return arguments_
}

export function effectiveVideoRequestsMatch(
  wizardCommand: VideoGenerationCommand,
  mcpArguments: Record<string, unknown>,
): boolean {
  return stableSerialize(mcpArgumentsFromCommand(wizardCommand)) === stableSerialize(mcpArguments)
}

export const videoGenerationCapability = {
  name: 'generation_video' as const,
  title: 'Generate Wan 2.1 Text2Video',
  description: 'Admit a typed generation.video job for an installed t2v or t2v_1.3B model in an explicit workspace.',
  useWhen: 'The user explicitly asks to generate video with the shared Wizard/MCP command.',
  parameters: [
    'intent_id', 'workspace', 'prompt', 'model_type', 'resolution', 'video_length',
    'duration_seconds', 'num_inference_steps', 'guidance_scale', 'seed',
    'negative_prompt', 'image_start', 'workspace_collection_id', 'confirm',
  ],
  inputSchema: {
    type: 'object',
    additionalProperties: false,
    properties: {
      type: { const: 'generation_video' },
      intent_id: { type: 'string', minLength: 1, maxLength: 160 },
      workspace: { type: 'string', minLength: 1, maxLength: 240 },
      prompt: { type: 'string', minLength: 1, maxLength: MAX_PROMPT },
      model_type: { type: 'string', enum: [...VIDEO_MODEL_TYPES] },
      resolution: { type: 'string' },
      video_length: { type: 'integer', minimum: 5, maximum: 10_000 },
      duration_seconds: { type: 'number', exclusiveMinimum: 0 },
      num_inference_steps: { type: 'integer', minimum: 1, maximum: 1000 },
      guidance_scale: { type: 'number' },
      seed: { type: 'integer' },
      negative_prompt: { type: 'string' },
      image_start: { type: ['string', 'null'] },
      workspace_collection_id: { type: 'string', minLength: 1, maxLength: 200 },
      confirm: { const: true },
    },
    required: ['type', 'intent_id', 'workspace', 'prompt', 'confirm'],
  },
  risk: 'compute' as const,
  confirmation: 'required' as const,
  progress: 'Admitting Wan Text2Video…',
  resolve: resolveVideoGenerationAction,
  validate: validateVideoGenerationAction,
  presentation: { destination: 'studio' as const, anchors: ['video', 'generate', 'destination'], replay: 'atomic' as const },
}

export function registerVideoGenerationCapability(
  register: (definition: typeof videoGenerationCapability) => unknown,
): void {
  register(videoGenerationCapability)
}
