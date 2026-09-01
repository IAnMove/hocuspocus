import * as api from '../../api/client'
import { commandResultFromSlice, type CommandResult } from '../../lib/commandContract'
import { getFamiliesForMode, getModelsForFamily, useStore } from '../../stores/useStore'
import type { ModelDef } from '../../types'
import type {
  AttachStudioReferencesCommand,
  ConfigureStudioLorasCommand,
  Prepare3dCommand,
  PrepareAudioCommand,
  PrepareImageCommand,
  PrepareVideoCommand,
  QueueSfxPackCommand,
} from './commands'

export type StudioSfxClip = {
  name: string
  prompt: string
  durationSeconds: number
}

const AUDIO_SUB_MODE_DEFAULTS: Record<PrepareAudioCommand['subMode'], string> = {
  speech: 'kugelaudio_0_open',
  music: 'ace_step_v1_5_xl_sft_lm_4b',
  sfx: 'mmaudio_v2',
}

let prepared3dPreset = 'balanced'

function workspaceId(): string {
  return useStore.getState().activeWorkspace || 'default'
}

function studioResult(
  mode: 'video' | 'image' | 'audio' | '3d' | 'generation',
  title: string,
  message: string,
  extra: { taskId?: string } = {},
): CommandResult {
  const entity = {
    kind: mode === 'generation' ? 'generation_task' : 'studio_form',
    id: extra.taskId || mode,
    workspaceId: workspaceId(),
  }
  return commandResultFromSlice({
    entity,
    taskIds: extra.taskId ? [extra.taskId] : undefined,
    artifacts: [{
      id: 'reply',
      kind: 'document',
      owner: entity,
      uri: 'studio:reply',
      metadata: { summary: message, title, mode },
    }],
  })
}

function visibleT2vModels(models: ModelDef[]): ModelDef[] {
  const enabledModels = useStore.getState().enabledModels
  const families = getFamiliesForMode('video', useStore.getState().families)
  const familyIds = new Set(families.map(family => family.id))
  const ordered = families.flatMap(family => getModelsForFamily(family.id, models, 'video'))
  const orderedIds = new Set(ordered.map(model => model.model_type))
  const extras = models.filter(model => familyIds.has(model.family) && !orderedIds.has(model.model_type))
  return [...ordered, ...extras].filter(model => (
    model.is_t2v
    && !model.tool_only
    && enabledModels.has(model.model_type)
    && model.is_downloaded !== false
  ))
}

function visibleImageModels(models: ModelDef[]): ModelDef[] {
  const enabledModels = useStore.getState().enabledModels
  const families = getFamiliesForMode('image', useStore.getState().families)
  const familyIds = new Set(families.map(family => family.id))
  const ordered = families.flatMap(family => getModelsForFamily(family.id, models, 'image'))
  const orderedIds = new Set(ordered.map(model => model.model_type))
  const extras = models.filter(model => familyIds.has(model.family) && !orderedIds.has(model.model_type))
  return [...ordered, ...extras].filter(model => (
    !model.tool_only
    && enabledModels.has(model.model_type)
    && model.is_downloaded !== false
  ))
}

export function openStudioAudio(subMode: PrepareAudioCommand['subMode']): void {
  const state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setSidebarMode('studio')
  state.setSidebarOpen(true)
  state.setGenerationMode('audio')
  state.setAudioSubMode(subMode)
}

export async function selectAudioModel(
  preferred?: string,
  subMode: PrepareAudioCommand['subMode'] = 'sfx',
): Promise<string> {
  let state = useStore.getState()
  if (!state.modelsLoaded) await state.loadModels()
  state = useStore.getState()
  const fallback = AUDIO_SUB_MODE_DEFAULTS[subMode]
  const requested = preferred && state.models.some(model => model.model_type === preferred)
    ? preferred
    : state.params.model_type && state.models.some(model => model.model_type === state.params.model_type)
      ? state.params.model_type
      : fallback
  if (requested && state.params.model_type !== requested) {
    state.selectModel(requested)
  }
  const selected = useStore.getState().params.model_type || requested || fallback
  const selectedModel = useStore.getState().models.find(model => model.model_type === selected)
  return selectedModel?.name || selected
}

export async function queueSfxPack(action: QueueSfxPackCommand): Promise<CommandResult> {
  if (!action.confirm) throw new Error('Encolar el pack de SFX requiere confirm=true tras una petición explícita.')
  if (!action.clips.length) throw new Error('El pack de SFX no incluye clips.')
  openStudioAudio('sfx')
  await selectAudioModel(action.modelType, 'sfx')
  const ids: string[] = []
  const negative = action.negativePrompt || 'music, speech, talking, vocals, long melody'
  for (const clip of action.clips) {
    applySfxClip(clip, negative)
    const before = new Set(useStore.getState().jobs)
    await useStore.getState().startGeneration()
    const created = useStore.getState().jobs.find(job => !before.has(job))
    if (!created) throw new Error(`HocusPocus no encoló el efecto ${clip.name}.`)
    if (created.status === 'failed') throw new Error(created.error || created.message || `Falló ${clip.name}.`)
    ids.push(`${clip.name}${created.id ? ` (${created.id})` : ''}`)
  }
  return studioResult(
    'audio',
    'Audio → SFX',
    [
      `He encolado **${ids.length} efectos SFX** en Studio → Audio → SFX.`,
      'Irán detrás de lo que ya use la GPU y aparecerán en la galería Audios al terminar.',
      '',
      ...ids.map(id => `- ${id}`),
    ].join('\n'),
  )
}

export function applySfxClip(clip: StudioSfxClip, negativePrompt: string): void {
  const state = useStore.getState()
  state.setDurationSeconds(Math.max(1, Math.min(20, clip.durationSeconds)))
  state.setParams({
    prompt: clip.prompt,
    MMAudio_prompt: clip.prompt,
    MMAudio_neg_prompt: negativePrompt || 'music, speech, talking, vocals, long melody',
    video_guide: undefined,
  })
}

export async function prepareVideo(action: PrepareVideoCommand): Promise<CommandResult> {
  let state = useStore.getState()
  if (!state.modelsLoaded) await state.loadModels()

  state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setSidebarMode('studio')
  state.setSidebarOpen(true)
  state.setGenerationMode('video')
  state.setMediaFilter('videos')

  state = useStore.getState()
  const candidates = visibleT2vModels(state.models)
  const requested = action.modelType
    ? candidates.find(model => model.model_type === action.modelType)
    : undefined
  if (action.modelType && !requested) {
    throw new Error(`El modelo ${action.modelType} no está instalado, habilitado o no admite texto a vídeo.`)
  }
  const current = candidates.find(model => model.model_type === state.params.model_type)
  const selected = requested || current || candidates.find(model => model.is_downloaded) || candidates[0]
  if (!selected) {
    throw new Error('No hay ningún modelo texto-a-vídeo instalado y habilitado.')
  }

  if (state.params.model_type !== selected.model_type) state.selectModel(selected.model_type)
  await useStore.getState().loadModelOptions(selected.model_type)

  state = useStore.getState()
  state.setStartImage(null)
  state.setEndImage(null)
  state.setPromptSchedulerEnabled(false)
  state.setOutputCount(action.outputCount ?? 1)
  if (action.aspectRatio) state.setAspectRatio(action.aspectRatio)
  if (action.resolutionPreset) state.setResolutionPreset(action.resolutionPreset)
  if (action.durationSeconds !== undefined) state.setDurationSeconds(action.durationSeconds)

  const params: Record<string, unknown> = {
    prompt: action.prompt,
    image_mode: 0,
    image_start: undefined,
    image_end: undefined,
    image_prompt_type: '',
    minimax_h3_references: undefined,
    h3_ref_videos: [],
    h3_ref_audios: [],
  }
  if (action.resolution) params.resolution = action.resolution
  if (action.negativePrompt !== undefined) params.negative_prompt = action.negativePrompt
  if (action.seed !== undefined) params.seed = action.seed
  if (action.inferenceSteps !== undefined) params.num_inference_steps = action.inferenceSteps
  if (action.guidanceScale !== undefined) params.guidance_scale = action.guidanceScale
  if (action.audioDirection !== undefined) params.h3_audio_prompt = action.audioDirection
  if (action.turbo !== undefined) params.minimax_h3_turbo_mode = action.turbo
  state.setParams(params)

  return studioResult(
    'video',
    'Video',
    `He preparado Studio → Video con ${selected.name}, ${useStore.getState().durationSeconds.toFixed(1)} s y el prompt indicado.`,
  )
}

export async function prepareImage(action: PrepareImageCommand): Promise<CommandResult> {
  let state = useStore.getState()
  if (!state.modelsLoaded) await state.loadModels()

  state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setSidebarMode('studio')
  state.setSidebarOpen(true)
  state.setGenerationMode('image')
  state.setMediaFilter('images')

  state = useStore.getState()
  const candidates = visibleImageModels(state.models)
  const requested = action.modelType
    ? candidates.find(model => model.model_type === action.modelType)
    : undefined
  if (action.modelType && !requested) {
    throw new Error(`El modelo ${action.modelType} no está instalado, habilitado o no admite texto a imagen.`)
  }
  const current = candidates.find(model => model.model_type === state.params.model_type)
  const selected = requested || current || candidates.find(model => model.is_downloaded) || candidates[0]
  if (!selected) {
    throw new Error('No hay ningún modelo de imagen instalado y habilitado.')
  }

  if (state.params.model_type !== selected.model_type) state.selectModel(selected.model_type)
  await useStore.getState().loadModelOptions(selected.model_type)

  state = useStore.getState()
  state.setStartImage(null)
  state.setEndImage(null)
  state.setOutputCount(action.outputCount ?? 1)
  if (action.aspectRatio) state.setAspectRatio(action.aspectRatio)
  if (action.resolutionPreset) state.setResolutionPreset(action.resolutionPreset)

  const params: Record<string, unknown> = {
    prompt: action.prompt,
    image_mode: 1,
    video_length: 1,
    image_start: undefined,
    image_end: undefined,
    image_prompt_type: '',
  }
  if (action.resolution) params.resolution = action.resolution
  if (action.negativePrompt !== undefined) params.negative_prompt = action.negativePrompt
  if (action.seed !== undefined) params.seed = action.seed
  if (action.inferenceSteps !== undefined) params.num_inference_steps = action.inferenceSteps
  if (action.guidanceScale !== undefined) params.guidance_scale = action.guidanceScale
  state.setParams(params)

  const resolution = useStore.getState().params.resolution || useStore.getState().resolutionPreset
  return studioResult(
    'image',
    'Image',
    `He preparado Studio → Image con ${selected.name}, ${resolution} y el prompt indicado.`,
  )
}

export async function prepare3d(action: Prepare3dCommand): Promise<CommandResult> {
  let state = useStore.getState()
  if (!state.modelsLoaded) await state.loadModels()
  state = useStore.getState()
  state.setSettingsOpen(false)
  state.setDashboardOpen(false)
  state.setSidebarMode('studio')
  state.setSidebarOpen(true)
  state.setGenerationMode('model3d')
  state.setMediaFilter('model3d')

  state = useStore.getState()
  const families = getFamiliesForMode('model3d', state.families)
  const candidates = families.flatMap(family => getModelsForFamily(family.id, state.models, 'model3d'))
    .filter(model => !model.tool_only)
  const requested = action.modelType
    ? candidates.find(model => model.model_type === action.modelType)
    : undefined
  if (action.modelType && !requested) {
    throw new Error(`El modelo 3D ${action.modelType} no está disponible.`)
  }
  const current = candidates.find(model => model.model_type === state.params.model_type)
  const selected = requested || current || candidates[0]
  if (!selected) throw new Error('No hay ningún modelo Hunyuan3D disponible.')
  if (state.params.model_type !== selected.model_type) state.selectModel(selected.model_type)
  useStore.getState().setParams({
    prompt: action.prompt,
    seed: action.seed ?? 1234,
  })
  prepared3dPreset = action.preset || 'balanced'
  return studioResult(
    '3d',
    '3D',
    `He preparado Studio → 3D con ${selected.name}, preset ${prepared3dPreset} y el prompt indicado. La pestaña 3D solo muestra resultados; la creación queda en Studio.`,
  )
}

export async function prepareAudio(action: PrepareAudioCommand): Promise<CommandResult> {
  openStudioAudio(action.subMode)
  const modelName = await selectAudioModel(action.modelType, action.subMode)
  const state = useStore.getState()
  if (action.subMode === 'sfx') {
    applySfxClip({
      name: 'sfx',
      prompt: action.prompt,
      durationSeconds: action.durationSeconds ?? 2,
    }, action.negativePrompt || '')
  } else {
    state.setDurationSeconds(action.durationSeconds ?? state.durationSeconds)
    state.setParams({
      prompt: action.prompt,
      negative_prompt: action.negativePrompt || '',
    })
  }
  const duration = useStore.getState().durationSeconds
  const room = action.subMode === 'sfx' ? 'SFX' : action.subMode === 'music' ? 'Music' : 'Speech'
  return studioResult(
    'audio',
    `Audio → ${room}`,
    `He preparado Studio → Audio → ${room} con ${modelName}, ${duration.toFixed(0)} s y el prompt indicado. La pestaña Audios solo muestra resultados; la creación queda en Studio.`,
  )
}

export async function startPreparedGeneration(): Promise<CommandResult> {
  const state = useStore.getState()
  if (state.generationMode === 'model3d') {
    const { startHunyuan3DJob } = await import('../../api/client')
    const job = await startHunyuan3DJob({
      operation: 'generate',
      model_id: String(state.params.model_type || ''),
      prompt: String(state.params.prompt || ''),
      workspace: state.activeWorkspace || 'default',
      preset: prepared3dPreset,
      seed: typeof state.params.seed === 'number' ? state.params.seed : 1234,
    })
    if (!job.job_id) throw new Error('Hunyuan3D devolvió éxito sin jobId; no considero la generación encolada.')
    return studioResult(
      'generation',
      'Studio generation',
      `He enviado el modelo 3D a Hunyuan3D (${job.job_id}). Aparecerá en la galería 3D al terminar.`,
      { taskId: job.job_id },
    )
  }
  const before = useStore.getState().jobs
  const knownJobs = new Set(before)
  await useStore.getState().startGeneration()
  const created = useStore.getState().jobs.find(job => !knownJobs.has(job))
  if (!created) throw new Error('HocusPocus no creó una tarea; revisa los requisitos del modelo y los campos visibles.')
  if (created.status === 'failed') throw new Error(created.error || created.message || 'La generación no pudo entrar en cola.')
  if (!created.id) throw new Error('HocusPocus devolvió éxito sin taskId; no considero la generación encolada.')
  const mode = useStore.getState().generationMode
  const kind = mode === 'image' ? 'imagen' : mode === 'audio' ? 'pista de audio' : 'vídeo'
  return studioResult(
    'generation',
    'Studio generation',
    `He enviado la ${kind} a la cola (${created.id}).`,
    { taskId: created.id },
  )
}

const normalized = (value: string): string => value.trim().toLocaleLowerCase()

async function imageOutputFiles(names: string[]): Promise<File[]> {
  const workspace = useStore.getState().activeWorkspace || 'default'
  const { outputs } = await api.fetchOutputs(0, 0, { workspace, mediaType: 'image' })
  const byName = new Map(outputs.map(output => [normalized(output.name), output]))
  const files: File[] = []
  for (const requestedName of names) {
    const output = byName.get(normalized(requestedName))
    if (!output) {
      throw new Error(`No existe la imagen “${requestedName}” en el workspace activo; no he inventado ni sustituido la referencia.`)
    }
    const response = await fetch(api.getFileUrl(output.name, workspace))
    if (!response.ok) throw new Error(`No pude leer la imagen “${output.name}” para usarla como referencia.`)
    const blob = await response.blob()
    files.push(new File([blob], output.name, { type: blob.type || 'image/png' }))
  }
  return files
}

function clearImageReferences(): void {
  const state = useStore.getState()
  for (let index = state.imageRefs.length - 1; index >= 0; index -= 1) {
    useStore.getState().removeImageRef(index)
  }
}

export async function attachStudioReferences(action: AttachStudioReferencesCommand): Promise<CommandResult> {
  let state = useStore.getState()
  if (state.generationMode !== 'image' && state.generationMode !== 'video') {
    throw new Error('Las referencias visuales sólo pueden adjuntarse a Studio → Image o Studio → Video.')
  }
  const selectedModel = state.models.find(model => model.model_type === state.params.model_type)
  if (!selectedModel) throw new Error('Studio no tiene un modelo de imagen/vídeo válido seleccionado.')
  const files = await imageOutputFiles(action.outputNames)

  if (action.role === 'start_frame') {
    if (state.generationMode !== 'video' || !selectedModel.is_i2v) {
      throw new Error(`${selectedModel.name} no admite una imagen inicial en el modo actual.`)
    }
    if (action.replaceExisting) state.setStartImage(null)
    state.setStartImage(files[0])
    return studioResult('image', 'Image / Video', `He adjuntado “${files[0].name}” como start frame de Studio → Video.`)
  }

  const config = state.modelOptions?.image_ref_choices
  const choices = config?.choices?.map(([, value]) => value) || []
  const desiredType = action.role === 'style' ? 'KI' : 'I'
  const supportsDesiredType = desiredType === 'KI'
    ? choices.some(value => value.includes('K'))
    : choices.some(value => value === 'I')
  if (!config || !supportsDesiredType) {
    throw new Error(`${selectedModel.name} no admite referencias de ${action.role === 'style' ? 'estilo/escenario' : 'sujeto'} en este formulario.`)
  }
  const configuredLimit = state.modelOptions?.max_image_refs
  const existingCount = action.replaceExisting ? 0 : state.imageRefs.length
  if (configuredLimit != null && existingCount + files.length > configuredLimit) {
    throw new Error(`${selectedModel.name} admite como máximo ${configuredLimit} referencias; se solicitaron ${existingCount + files.length}.`)
  }
  if (action.replaceExisting) clearImageReferences()
  files.forEach(file => useStore.getState().addImageRef(file))
  state = useStore.getState()
  state.setImageRefType(desiredType)
  state.setRemoveBackgroundRefs(action.removeBackground)
  if (state.modelOptions?.architecture === 'minimax_h3') {
    state.setParam('h3_reference_mode', 'references')
  }
  return studioResult(
    'image',
    'Image / Video',
    `He adjuntado ${files.length} referencia${files.length === 1 ? '' : 's'} de ${action.role === 'style' ? 'estilo/escenario' : 'sujeto'} a Studio usando nombres reales del workspace.`,
  )
}

export async function configureStudioLoras(action: ConfigureStudioLorasCommand): Promise<CommandResult> {
  let state = useStore.getState()
  if (state.generationMode !== 'image' && state.generationMode !== 'video') {
    throw new Error('Los LoRAs sólo pueden configurarse en Studio → Image o Studio → Video.')
  }
  const modelType = state.params.model_type
  if (!modelType) throw new Error('Studio no tiene un modelo seleccionado para consultar LoRAs compatibles.')
  await state.loadLoras(modelType)
  state = useStore.getState()
  const availableByName = new Map(state.availableLoras.map(name => [normalized(name), name]))
  const resolved = action.loras.map(selection => {
    const filename = availableByName.get(normalized(selection.name))
    if (!filename) {
      throw new Error(`El LoRA “${selection.name}” no está instalado o no es compatible con ${modelType}; no lo he activado.`)
    }
    return { ...selection, name: filename }
  })
  const requested = new Set(resolved.map(selection => selection.name))
  if (action.replaceExisting) {
    for (const active of [...(useStore.getState().params.activated_loras || [])]) {
      if (!requested.has(active)) useStore.getState().toggleLora(active)
    }
  }
  for (const selection of resolved) {
    if (!(useStore.getState().params.activated_loras || []).includes(selection.name)) {
      useStore.getState().toggleLora(selection.name)
    }
    const phases = Math.max(1, useStore.getState().modelOptions?.guidance_max_phases || 1)
    for (let phase = 0; phase < phases; phase += 1) {
      useStore.getState().setLoraWeight(selection.name, phase, selection.weight)
    }
  }
  const active = useStore.getState().params.activated_loras || []
  if (!active.length) {
    return studioResult('image', 'Image / Video', 'He desactivado todos los LoRAs de Studio para el modelo actual.')
  }
  return studioResult(
    'image',
    'Image / Video',
    `He configurado ${active.length} LoRA${active.length === 1 ? '' : 's'} compatible${active.length === 1 ? '' : 's'} en Studio: ${active.join(', ')}.`,
  )
}
