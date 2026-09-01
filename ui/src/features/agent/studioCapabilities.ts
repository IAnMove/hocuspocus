/**
 * Canonical capability definitions for the Studio family.
 *
 * The visible form mutations intentionally live behind lazy bridges exported
 * by agentActions.ts.  That keeps this registry module free of a runtime
 * agentActions import and, in turn, avoids an initialization cycle when the
 * parent capability registry imports this file as a side effect.
 */
import type { defineCapability, CapabilityDefinition, CapabilityExecutionContext, CapabilityExecutionOutcome } from './capabilityRegistry'
import type {
  AgentAction,
  AgentAttachStudioReferencesAction,
  AgentConfigureStudioLorasAction,
  AgentPrepare3dAction,
  AgentPrepareAudioAction,
  AgentPrepareImageAction,
  AgentPrepareVideoAction,
  AgentQueueSfxPackAction,
  AgentStartGenerationAction,
} from './agentActions'
import type { AspectRatio, ResolutionPreset } from '../../types'

const RESOLUTION_PRESETS = new Set<ResolutionPreset>(['auto', '480p', '540p', '720p', '768p', '1080p'])
const ASPECT_RATIOS = new Set<AspectRatio>(['auto', '21:9', '16:9', '9:16', '1:1', '4:3', '3:4'])
const AUDIO_SUB_MODES = new Set<AgentPrepareAudioAction['subMode']>(['speech', 'music', 'sfx'])
const REFERENCE_ROLES = new Set<AgentAttachStudioReferencesAction['role']>(['start_frame', 'subject', 'style'])

function text(value: unknown, maxLength: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
}

function number(
  value: unknown,
  minimum: number,
  maximum: number,
  integer = false,
): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  const bounded = Math.max(minimum, Math.min(maximum, value))
  return integer ? Math.round(bounded) : bounded
}

function stringArray(value: unknown, maxItems: number, maxLength: number): string[] {
  return Array.isArray(value)
    ? value.slice(0, maxItems).flatMap(item => {
      const value = text(item, maxLength)
      return value ? [value] : []
    })
    : []
}

function studioTarget(mode: 'video' | 'image' | 'audio' | '3d', title: string) {
  return { kind: 'studio_form', id: mode, title: `Studio → ${title}` }
}

function commonPresentation(anchors: string[]) {
  return { destination: 'studio' as const, anchors, replay: 'atomic' as const }
}

function videoAction(raw: Record<string, unknown>): AgentPrepareVideoAction | null {
  const prompt = text(raw.prompt, 8_000)
  if (!prompt) return null
  const resolutionPreset = text(raw.resolution_preset, 12) as ResolutionPreset
  const aspectRatio = text(raw.aspect_ratio, 12) as AspectRatio
  const resolution = text(raw.resolution, 20)
  const turbo = raw.turbo === 'on' ? true : raw.turbo === 'off' ? false : undefined
  return {
    type: 'prepare_video',
    prompt,
    modelType: text(raw.model_type, 160) || undefined,
    durationSeconds: number(raw.duration_seconds, 1, 300),
    resolutionPreset: RESOLUTION_PRESETS.has(resolutionPreset) ? resolutionPreset : undefined,
    resolution: /^\d{2,4}x\d{2,4}$/.test(resolution) ? resolution : undefined,
    aspectRatio: ASPECT_RATIOS.has(aspectRatio) ? aspectRatio : undefined,
    negativePrompt: text(raw.negative_prompt, 2_000) || undefined,
    seed: number(raw.seed, -1, 2_147_483_647, true),
    inferenceSteps: number(raw.inference_steps, 1, 100, true),
    guidanceScale: number(raw.guidance_scale, 0, 30),
    outputCount: number(raw.output_count, 1, 8, true),
    audioDirection: text(raw.audio_direction, 1_000) || undefined,
    turbo,
  }
}

function imageAction(raw: Record<string, unknown>): AgentPrepareImageAction | null {
  const prompt = text(raw.prompt, 8_000)
  if (!prompt) return null
  const resolutionPreset = text(raw.resolution_preset, 12) as ResolutionPreset
  const aspectRatio = text(raw.aspect_ratio, 12) as AspectRatio
  const resolution = text(raw.resolution, 20)
  return {
    type: 'prepare_image',
    prompt,
    modelType: text(raw.model_type, 160) || undefined,
    resolutionPreset: RESOLUTION_PRESETS.has(resolutionPreset) ? resolutionPreset : undefined,
    resolution: /^\d{2,4}x\d{2,4}$/.test(resolution) ? resolution : undefined,
    aspectRatio: ASPECT_RATIOS.has(aspectRatio) ? aspectRatio : undefined,
    negativePrompt: text(raw.negative_prompt, 2_000) || undefined,
    seed: number(raw.seed, -1, 2_147_483_647, true),
    inferenceSteps: number(raw.inference_steps, 1, 100, true),
    guidanceScale: number(raw.guidance_scale, 0, 30),
    outputCount: number(raw.output_count, 1, 8, true),
  }
}

function audioAction(raw: Record<string, unknown>): AgentPrepareAudioAction | null {
  const prompt = text(raw.prompt, 8_000)
  if (!prompt) return null
  const subMode = text(raw.audio_sub_mode, 12) as AgentPrepareAudioAction['subMode']
  return {
    type: 'prepare_audio',
    subMode: AUDIO_SUB_MODES.has(subMode) ? subMode : 'sfx',
    prompt,
    modelType: text(raw.model_type, 160) || undefined,
    durationSeconds: number(raw.duration_seconds, 1, 20),
    negativePrompt: text(raw.negative_prompt, 2_000) || undefined,
  }
}

function model3dAction(raw: Record<string, unknown>): AgentPrepare3dAction | null {
  const prompt = text(raw.prompt, 8_000)
  if (!prompt) return null
  return {
    type: 'prepare_3d',
    prompt,
    modelType: text(raw.model_type, 160) || undefined,
    preset: text(raw.preset, 40) || undefined,
    seed: number(raw.seed, -1, 2_147_483_647, true),
  }
}

function sfxAction(raw: Record<string, unknown>): AgentQueueSfxPackAction | null {
  if (raw.confirm !== true) return null
  const clips = Array.isArray(raw.sfx_clips)
    ? raw.sfx_clips.slice(0, 12).flatMap(item => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return []
      const record = item as Record<string, unknown>
      const name = text(record.name, 80)
      const prompt = text(record.prompt, 1_500)
      if (!name || !prompt) return []
      return [{ name, prompt, durationSeconds: number(record.duration_seconds, 1, 20) ?? 1 }]
    })
    : []
  if (!clips.length) return null
  return {
    type: 'queue_sfx_pack',
    style: text(raw.visual_style, 2_000) || text(raw.theme, 1_000),
    clips,
    modelType: text(raw.model_type, 160) || undefined,
    negativePrompt: text(raw.negative_prompt, 2_000) || undefined,
    confirm: true,
  }
}

function referencesAction(raw: Record<string, unknown>): AgentAttachStudioReferencesAction | null {
  const outputNames = stringArray(raw.reference_output_names, 12, 300)
  if (!outputNames.length) return null
  const role = text(raw.reference_role, 30) as AgentAttachStudioReferencesAction['role']
  return {
    type: 'attach_studio_references',
    outputNames,
    role: REFERENCE_ROLES.has(role) ? role : 'subject',
    replaceExisting: raw.replace_existing !== false,
    removeBackground: raw.remove_background === true,
  }
}

function lorasAction(raw: Record<string, unknown>): AgentConfigureStudioLorasAction | null {
  const loras = Array.isArray(raw.loras)
    ? raw.loras.slice(0, 12).flatMap(item => {
      if (!item || typeof item !== 'object' || Array.isArray(item)) return []
      const record = item as Record<string, unknown>
      const name = text(record.name, 300)
      return name ? [{ name, weight: number(record.weight, 0, 2) ?? 1 }] : []
    })
    : []
  if (!loras.length && raw.replace_existing !== true) return null
  return {
    type: 'configure_studio_loras',
    loras,
    replaceExisting: raw.replace_existing === true,
  }
}

function validType<T extends AgentAction>(type: T['type'], action: AgentAction): string[] {
  return action.type === type ? [] : [`${type} is invalid`]
}

async function bridgeSfx<TAction extends AgentAction>(
  action: TAction,
  _context: CapabilityExecutionContext,
): Promise<CapabilityExecutionOutcome> {
  if (action.type !== 'queue_sfx_pack') throw new Error(`No hay puente Studio para ${action.type}.`)
  const { queueSfxPackForAgent } = await import('./agentActions')
  return { message: await queueSfxPackForAgent(action), target: studioTarget('audio', 'Audio → SFX') }
}

/**
 * Register the Studio family after the core registry has finished evaluating.
 *
 * The registrar is injected by capabilityRegistry.ts instead of imported as a
 * runtime binding here.  This keeps the module safe in both directions: the
 * registry can import this file without an ESM temporal-dead-zone cycle, and
 * tests can exercise the family with an isolated collector.
 */
export function registerStudioCapabilities(register: typeof defineCapability): void {
  const studioDefinition = <TAction extends AgentAction>(
    definition: CapabilityDefinition<TAction>,
  ): CapabilityDefinition<TAction> => register(definition)

  studioDefinition<AgentPrepareVideoAction>({
  name: 'prepare_video',
  title: 'Prepare Studio video',
  description: 'Open Studio → Video and fill a validated text-to-video form.',
  useWhen: 'The user asks to prepare, show or fill a video generation form.',
  parameters: ['prompt', 'model_type', 'duration_seconds', 'resolution_preset', 'resolution', 'aspect_ratio', 'negative_prompt', 'seed', 'inference_steps', 'guidance_scale', 'output_count', 'audio_direction', 'turbo'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'prepare_video' }, prompt: { type: 'string', minLength: 1 }, model_type: { type: 'string' }, duration_seconds: { type: 'number' }, resolution_preset: { type: 'string', enum: [...RESOLUTION_PRESETS] }, resolution: { type: 'string' }, aspect_ratio: { type: 'string', enum: [...ASPECT_RATIOS] }, negative_prompt: { type: 'string' }, seed: { type: 'integer' }, inference_steps: { type: 'integer' }, guidance_scale: { type: 'number' }, output_count: { type: 'integer' }, audio_direction: { type: 'string' }, turbo: { type: 'string', enum: ['on', 'off'] } }, required: ['type', 'prompt'] },
  risk: 'edit', confirmation: 'none', progress: 'Rellenando Studio → Video…',
  resolve: videoAction,
  validate(action) { return action.prompt ? validType('prepare_video', action) : ['prompt is required'] },
  async prepare(action) { return action },
  async execute(action, context) { return context.adapters.studio.prepareVideo(action) },
  correlate(_action, outcome) { return outcome.target },
  async track(_action, outcome) { return outcome },
  report: { targetKind: 'studio_form', successState: 'prepared' },
  summarize(_action, outcome) { return outcome.message },
  presentation: commonPresentation(['prompt', 'model', 'generate']),
  })

  studioDefinition<AgentPrepareImageAction>({
  name: 'prepare_image',
  title: 'Prepare Studio image',
  description: 'Open Studio → Image and fill a validated text-to-image form.',
  useWhen: 'The user asks to prepare, show or fill an image generation form.',
  parameters: ['prompt', 'model_type', 'resolution_preset', 'resolution', 'aspect_ratio', 'negative_prompt', 'seed', 'inference_steps', 'guidance_scale', 'output_count'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'prepare_image' }, prompt: { type: 'string', minLength: 1 }, model_type: { type: 'string' }, resolution_preset: { type: 'string', enum: [...RESOLUTION_PRESETS] }, resolution: { type: 'string' }, aspect_ratio: { type: 'string', enum: [...ASPECT_RATIOS] }, negative_prompt: { type: 'string' }, seed: { type: 'integer' }, inference_steps: { type: 'integer' }, guidance_scale: { type: 'number' }, output_count: { type: 'integer' } }, required: ['type', 'prompt'] },
  risk: 'edit', confirmation: 'none', progress: 'Rellenando Studio → Image…',
  resolve: imageAction,
  validate(action) { return action.prompt ? validType('prepare_image', action) : ['prompt is required'] },
  async prepare(action) { return action },
  async execute(action, context) { return context.adapters.studio.prepareImage(action) },
  correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'studio_form', successState: 'prepared' }, summarize(_action, outcome) { return outcome.message },
  presentation: commonPresentation(['prompt', 'model', 'generate']),
  })

  studioDefinition<AgentPrepareAudioAction>({
  name: 'prepare_audio',
  title: 'Prepare Studio audio',
  description: 'Open Studio → Audio and fill Speech, Music or SFX.',
  useWhen: 'The user asks to prepare, show or fill a Studio audio form.',
  parameters: ['audio_sub_mode', 'prompt', 'model_type', 'duration_seconds', 'negative_prompt'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'prepare_audio' }, audio_sub_mode: { type: 'string', enum: [...AUDIO_SUB_MODES] }, prompt: { type: 'string', minLength: 1 }, model_type: { type: 'string' }, duration_seconds: { type: 'number' }, negative_prompt: { type: 'string' } }, required: ['type', 'prompt'] },
  risk: 'edit', confirmation: 'none', progress: 'Rellenando Studio → Audio…',
  resolve: audioAction,
  validate(action) { return action.prompt ? validType('prepare_audio', action) : ['prompt is required'] },
  async prepare(action) { return action },
  async execute(action, context) { return context.adapters.studio.prepareAudio(action) },
  correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'studio_form', successState: 'prepared' }, summarize(_action, outcome) { return outcome.message },
  presentation: commonPresentation(['audio-mode', 'prompt', 'model', 'generate']),
  })

  studioDefinition<AgentPrepare3dAction>({
  name: 'prepare_3d',
  title: 'Prepare Studio 3D',
  description: 'Open Studio → 3D and fill a validated text-to-mesh form.',
  useWhen: 'The user asks to prepare, show or fill a 3D generation form.',
  parameters: ['prompt', 'model_type', 'preset', 'seed'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'prepare_3d' }, prompt: { type: 'string', minLength: 1 }, model_type: { type: 'string' }, preset: { type: 'string' }, seed: { type: 'integer' } }, required: ['type', 'prompt'] },
  risk: 'edit', confirmation: 'none', progress: 'Rellenando Studio → 3D…',
  resolve: model3dAction,
  validate(action) { return action.prompt ? validType('prepare_3d', action) : ['prompt is required'] },
  async prepare(action) { return action },
  async execute(action, context) { return context.adapters.studio.prepare3d(action) },
  correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'studio_form', successState: 'prepared' }, summarize(_action, outcome) { return outcome.message },
  presentation: commonPresentation(['prompt', 'model', 'generate']),
  })

  studioDefinition<AgentQueueSfxPackAction>({
  name: 'queue_sfx_pack',
  title: 'Queue a Studio SFX pack',
  description: 'Open Studio → Audio → SFX and submit several one-shot effects.',
  useWhen: 'The user explicitly asks to generate or queue a pack of sound effects.',
  parameters: ['visual_style', 'theme', 'sfx_clips', 'model_type', 'negative_prompt', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'queue_sfx_pack' }, visual_style: { type: 'string' }, theme: { type: 'string' }, sfx_clips: { type: 'array', minItems: 1 }, model_type: { type: 'string' }, negative_prompt: { type: 'string' }, confirm: { const: true } }, required: ['type', 'sfx_clips', 'confirm'] },
  risk: 'compute', confirmation: 'required', progress: 'Encolando el pack de SFX…',
  resolve: sfxAction,
  validate(action) { return action.confirm === true && action.clips.length > 0 ? validType('queue_sfx_pack', action) : ['confirmed SFX clips are required'] },
  async prepare(action) { return action }, execute: bridgeSfx,
  correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'studio_sfx_pack', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: commonPresentation(['audio-mode', 'sfx-pack', 'queue']),
  })

  studioDefinition<AgentStartGenerationAction>({
  name: 'start_generation',
  title: 'Queue the prepared Studio job',
  description: 'Submit the Studio form prepared earlier in the same Wizard turn.',
  useWhen: 'The user asks to generate, start, launch or queue the prepared Studio media.',
  parameters: [],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'start_generation' }, confirm: { const: true } }, required: ['type', 'confirm'] },
  risk: 'compute', confirmation: 'required', progress: 'Enviando la generación de Studio a la cola…',
  resolve(raw) { return raw.type === 'start_generation' && raw.confirm === true ? { type: 'start_generation', confirm: true } : null },
  validate(action) { return validType('start_generation', action) },
  async prepare(action) { return action },
  async execute(action, context) { return context.adapters.studio.startGeneration(action) },
  correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'generation_task', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: commonPresentation(['generate', 'queue']),
  })

  studioDefinition<AgentAttachStudioReferencesAction>({
  name: 'attach_studio_references',
  title: 'Attach existing image outputs to Studio',
  description: 'Attach exact image outputs as Studio start-frame, subject or style references.',
  useWhen: 'The user asks to use existing generated images as Studio conditioning.',
  parameters: ['reference_output_names', 'reference_role', 'replace_existing', 'remove_background'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'attach_studio_references' }, reference_output_names: { type: 'array', minItems: 1 }, reference_role: { type: 'string', enum: [...REFERENCE_ROLES] }, replace_existing: { type: 'boolean' }, remove_background: { type: 'boolean' } }, required: ['type', 'reference_output_names'] },
  risk: 'edit', confirmation: 'none', progress: 'Adjuntando referencias a Studio…',
  resolve: referencesAction,
  validate(action) { return action.outputNames.length ? validType('attach_studio_references', action) : ['at least one exact output name is required'] },
  async prepare(action) { return action },
  async execute(action, context) { return context.adapters.studio.attachReferences(action) },
  correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'studio_form', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: commonPresentation(['references', 'prompt']),
  })

  studioDefinition<AgentConfigureStudioLorasAction>({
  name: 'configure_studio_loras',
  title: 'Configure compatible Studio LoRAs',
  description: 'Resolve and activate exact LoRA filenames compatible with the selected Studio model.',
  useWhen: 'The user asks to use, change or clear LoRAs in Studio Image or Video.',
  parameters: ['loras', 'replace_existing'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'configure_studio_loras' }, loras: { type: 'array' }, replace_existing: { type: 'boolean' } }, required: ['type'] },
  risk: 'edit', confirmation: 'none', progress: 'Configurando LoRAs compatibles en Studio…',
  resolve: lorasAction,
  validate(action) { return action.loras.length || action.replaceExisting ? validType('configure_studio_loras', action) : ['LoRA selections or replace_existing are required'] },
  async prepare(action) { return action },
  async execute(action, context) { return context.adapters.studio.configureLoras(action) },
  correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'studio_form', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: commonPresentation(['loras', 'model']),
  })
}
