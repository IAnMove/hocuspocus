/** Immutable generation.video command codec shared by product surfaces. */
import { stableSerialize } from './commandContract'
import { assertCanonicalAudioReference } from './canonicalAudioReference'

export const VIDEO_GENERATION_OPERATION = 'generation.video' as const
export const VIDEO_GENERATION_SCHEMA_VERSION = 2 as const
export const VIDEO_MODEL_FAMILY = 'wan_t2v_2_1' as const
export const VIDEO_MODEL_TYPES = ['t2v', 't2v_1.3B'] as const

export const WORKSPACE = /^(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)$/
const RESOLUTION = /^([1-9][0-9]{1,4})x([1-9][0-9]{1,4})$/
export const MAX_PROMPT = 200_000
export const MAX_INTENT = 160
const COMMAND_FIELDS = new Set(['version', 'operation', 'intent_id', 'input'])
const INPUT_FIELDS = new Set(['workspace', 'workspace_collection_id', 'params'])
const PARAM_FIELDS = new Set([
  'prompt', 'negative_prompt', 'model_type', 'resolution', 'video_length',
  'num_inference_steps', 'guidance_scale', 'seed', 'image_mode', 'generation_mode',
  'repeat_generation', 'batch_size', 'activated_loras', 'loras_multipliers',
  'image_start', 'image_end', 'image_refs', 'video_guide', 'video_source',
  'video_mask', 'image_prompt_type', 'video_prompt_type', 'prompt_enhancer',
  'flow_shift', 'sample_solver', 'guidance_phases', 'multi_prompts_gen_type',
])

export type VideoModelType = typeof VIDEO_MODEL_TYPES[number]

export interface VideoGenerationCommand {
  version: typeof VIDEO_GENERATION_SCHEMA_VERSION
  operation: typeof VIDEO_GENERATION_OPERATION
  intent_id: string
  input: {
    workspace: string
    workspace_collection_id?: string
    params: Record<string, unknown>
  }
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function requiredText(value: unknown, field: string, maximum: number): string {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`${field} must be a non-blank string`)
  if (value.length > maximum) throw new Error(`${field} is too long`)
  return value
}

function exactText(value: unknown, field: string, maximum: number): string {
  const text = requiredText(value, field, maximum)
  if (text !== value) throw new Error(`${field} must be exact`)
  return text
}

export function modelType(value: unknown): VideoModelType | null {
  return value === 't2v' || value === 't2v_1.3B' ? value : null
}

function resolutionSidesValid(width: number, height: number): boolean {
  return [width, height].every(size => size >= 64 && size <= 4096 && size % 8 === 0)
}

export function resolutionValue(value: unknown): string | null {
  if (typeof value !== 'string' || !RESOLUTION.test(value)) return null
  const match = RESOLUTION.exec(value)
  if (!match) return null
  return resolutionSidesValid(Number(match[1]), Number(match[2])) ? value : null
}

function assertAllowedKeys(value: Record<string, unknown>, allowed: Set<string>, prefix: string): void {
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) throw new Error(`${prefix}${key} is not supported by generation.video`)
  }
}

function assertCommandEnvelope(value: Record<string, unknown>): void {
  assertAllowedKeys(value, COMMAND_FIELDS, 'command.')
  if (value.version !== VIDEO_GENERATION_SCHEMA_VERSION) throw new Error('version must be the integer 2')
  if (value.operation !== VIDEO_GENERATION_OPERATION) throw new Error('operation must be generation.video')
  exactText(value.intent_id, 'intent_id', MAX_INTENT)
}

function assertCommandInput(input: unknown): Record<string, unknown> {
  if (!isRecord(input)) throw new Error('input must be an object')
  assertAllowedKeys(input, INPUT_FIELDS, 'input.')
  const workspace = exactText(input.workspace, 'input.workspace', 240)
  if (!WORKSPACE.test(workspace)) throw new Error('input.workspace must be an exact output workspace name')
  return input
}

function assertInactiveVideoSentinels(params: Record<string, unknown>): void {
  if (params.generation_mode !== undefined && params.generation_mode !== 'video') {
    throw new Error('input.params.generation_mode must be video')
  }
  if (params.image_mode !== undefined && params.image_mode !== 0) {
    throw new Error('input.params.image_mode must be 0')
  }
  if (params.image_start !== undefined) {
    assertCanonicalAudioReference(params.image_start, 'input.params.image_start', 'video')
  }
}

function assertVideoParams(params: unknown): void {
  if (!isRecord(params)) throw new Error('input.params must be an object')
  assertAllowedKeys(params, PARAM_FIELDS, 'input.params.')
  requiredText(params.prompt, 'input.params.prompt', MAX_PROMPT)
  if (!modelType(params.model_type)) throw new Error('input.params.model_type must be t2v or t2v_1.3B')
  if (!resolutionValue(params.resolution)) throw new Error('input.params.resolution is invalid')
  assertInactiveVideoSentinels(params)
}

export function assertVideoGenerationCommand(value: unknown): asserts value is VideoGenerationCommand {
  if (!isRecord(value)) throw new Error('generation.video command must be an object')
  assertCommandEnvelope(value)
  const input = assertCommandInput(value.input)
  assertVideoParams(input.params)
  stableSerialize(value)
}

export function detachedVideoGenerationCommand(value: unknown): VideoGenerationCommand {
  assertVideoGenerationCommand(value)
  return JSON.parse(stableSerialize(value)) as VideoGenerationCommand
}
