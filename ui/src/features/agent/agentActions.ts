import { getModelsForFamily, getFamiliesForMode, useStore } from '../../stores/useStore'
import type { AspectRatio, MediaFilter, ModelDef, ResolutionPreset } from '../../types'

export const AGENT_TABS = [
  'studio',
  'director',
  'productions',
  'images',
  'videos',
  'audio',
  '3d',
  'story_lab',
  'series_lab',
  'comics',
  'video_editor',
  'video_3d',
  'animate_3d',
  'character_creator',
  'character_kit',
  'workspaces',
  'settings',
] as const

export type AgentTab = typeof AGENT_TABS[number]

export interface AgentOpenTabAction {
  type: 'open_tab'
  tab: AgentTab
}

export interface AgentPrepareVideoAction {
  type: 'prepare_video'
  prompt: string
  modelType?: string
  durationSeconds?: number
  resolutionPreset?: ResolutionPreset
  resolution?: string
  aspectRatio?: AspectRatio
  negativePrompt?: string
  seed?: number
  inferenceSteps?: number
  guidanceScale?: number
  outputCount?: number
  audioDirection?: string
  turbo?: boolean
}

export interface AgentStartGenerationAction {
  type: 'start_generation'
}

export type AgentAction = AgentOpenTabAction | AgentPrepareVideoAction | AgentStartGenerationAction

export interface AgentTurn {
  reply: string
  actions: AgentAction[]
}

export interface AgentActionResult {
  action: AgentAction
  ok: boolean
  message: string
}

export interface AgentAppSnapshot {
  current: {
    media_filter: string
    sidebar_mode: string
    sidebar_open: boolean
    generation_mode: string
    selected_model: string
    prompt_preview: string
    duration_seconds: number
    resolution: string
    aspect_ratio: string
  }
  available_video_models: Array<{
    model_type: string
    name: string
    family: string
    installed: boolean
    enabled: boolean
    text_to_video: boolean
  }>
}

const TAB_SET = new Set<string>(AGENT_TABS)
const RESOLUTION_PRESETS = new Set<ResolutionPreset>(['auto', '480p', '540p', '720p', '768p', '1080p'])
const ASPECT_RATIOS = new Set<AspectRatio>(['auto', '21:9', '16:9', '9:16', '1:1', '4:3', '3:4'])
const MAX_ACTIONS = 6

const cleanString = (value: unknown, maxLength: number): string => (
  typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
)

const optionalNumber = (
  value: unknown,
  minimum: number,
  maximum: number,
  integer = false,
): number | undefined => {
  if (typeof value !== 'number' || !Number.isFinite(value)) return undefined
  const bounded = Math.max(minimum, Math.min(maximum, value))
  return integer ? Math.round(bounded) : bounded
}

const optionalPositiveNumber = (
  value: unknown,
  minimum: number,
  maximum: number,
  integer = false,
): number | undefined => (
  typeof value === 'number' && value > 0
    ? optionalNumber(value, minimum, maximum, integer)
    : undefined
)

const extractJsonObject = (raw: string): Record<string, unknown> | null => {
  const trimmed = raw.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')
  const start = trimmed.indexOf('{')
  const end = trimmed.lastIndexOf('}')
  if (start < 0 || end <= start) return null
  try {
    const parsed = JSON.parse(trimmed.slice(start, end + 1))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null
  } catch {
    return null
  }
}

function parseAction(value: unknown): AgentAction | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = value as Record<string, unknown>
  if (raw.type === 'open_tab') {
    const tab = cleanString(raw.tab, 40)
    return TAB_SET.has(tab) ? { type: 'open_tab', tab: tab as AgentTab } : null
  }
  if (raw.type === 'prepare_video') {
    const prompt = cleanString(raw.prompt, 8_000)
    if (!prompt) return null
    const resolutionPreset = cleanString(raw.resolution_preset, 12) as ResolutionPreset
    const aspectRatio = cleanString(raw.aspect_ratio, 12) as AspectRatio
    const resolution = cleanString(raw.resolution, 20)
    const turbo = raw.turbo === 'on' ? true : raw.turbo === 'off' ? false : undefined
    return {
      type: 'prepare_video',
      prompt,
      modelType: cleanString(raw.model_type, 160) || undefined,
      durationSeconds: optionalPositiveNumber(raw.duration_seconds, 1, 300),
      resolutionPreset: RESOLUTION_PRESETS.has(resolutionPreset) ? resolutionPreset : undefined,
      resolution: /^\d{2,4}x\d{2,4}$/.test(resolution) ? resolution : undefined,
      aspectRatio: ASPECT_RATIOS.has(aspectRatio) ? aspectRatio : undefined,
      negativePrompt: cleanString(raw.negative_prompt, 2_000) || undefined,
      seed: optionalNumber(raw.seed, -1, 2_147_483_647, true),
      inferenceSteps: optionalPositiveNumber(raw.inference_steps, 1, 100, true),
      guidanceScale: typeof raw.guidance_scale === 'number' && raw.guidance_scale >= 0
        ? optionalNumber(raw.guidance_scale, 0, 30)
        : undefined,
      outputCount: optionalPositiveNumber(raw.output_count, 1, 8, true),
      audioDirection: cleanString(raw.audio_direction, 1_000) || undefined,
      turbo,
    }
  }
  if (raw.type === 'start_generation') return { type: 'start_generation' }
  return null
}

/**
 * Treat model output as an untrusted proposal. Only known actions and bounded
 * fields survive, and generation can start only after this same turn prepared
 * a video. That prevents stale chat context from firing the current form.
 */
export function parseAgentTurn(raw: string): AgentTurn {
  const object = extractJsonObject(raw)
  if (!object) return { reply: raw.trim(), actions: [] }
  const reply = cleanString(object.reply, 8_000)
  const proposed = Array.isArray(object.actions) ? object.actions.slice(0, MAX_ACTIONS) : []
  const actions: AgentAction[] = []
  let preparedVideo = false
  let startedGeneration = false
  for (const value of proposed) {
    const action = parseAction(value)
    if (!action) continue
    if (action.type === 'prepare_video') preparedVideo = true
    if (action.type === 'start_generation') {
      if (!preparedVideo || startedGeneration) continue
      startedGeneration = true
    }
    actions.push(action)
  }
  return {
    reply: reply || (actions.length ? 'El hechizo está trazado; voy a mover HocusPocus.' : raw.trim()),
    actions,
  }
}

const EXPLICIT_VIDEO_REQUESTS = [
  /\b(?:hazme|hacedme|generame|genérame|creame|créame)\b[^.!?\n]*\b(?:video|vídeo|clip)\b/i,
  /\b(?:haz|haced|genera|generad|crea|cread|lanza|lanzad|renderiza|renderizad|encola|encolad)\b[^.!?\n]*\b(?:video|vídeo|clip)\b/i,
  /\b(?:quiero|quisiera)\s+que\s+(?:me\s+)?(?:hagas|generes|crees|lances|pongas\s+en\s+marcha|env[ií]es)\b[^.!?\n]*\b(?:video|vídeo|clip)\b/i,
  /\b(?:puedes|podr[ií]as)\s+(?:hacerme|generarme|crearme|lanzar|poner\s+en\s+marcha|enviar)\b[^.!?\n]*\b(?:video|vídeo|clip)\b/i,
  /\b(?:ponme|pones|pon|poned)\b[^.!?\n]*\ben\s+marcha\b[^.!?\n]*\b(?:video|vídeo|clip)\b/i,
  /\b(?:pon|poned)\b[^.!?\n]*\b(?:video|vídeo|clip)\b[^.!?\n]*\b(?:en\s+marcha|a\s+generar|en\s+cola)\b/i,
  /\b(?:manda|mandad|env[ií]a|enviad)\b[^.!?\n]*\b(?:video|vídeo|clip)\b[^.!?\n]*\b(?:cola|generaci[oó]n)\b/i,
  /\b(?:make|create|generate|render|launch|start|queue)\b[^.!?\n]*\b(?:video|clip)\b/i,
]

const NEGATED_VIDEO_REQUEST = /\b(?:no|sin|don['’]?t|do\s+not)\b[^.!?\n]{0,32}\b(?:hagas|generes|crees|lances|encoles|hacer|generar|crear|lanzar|encolar|make|create|generate|render|launch|start|queue)\b/i

export function isExplicitVideoGenerationRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text)) return false
  return EXPLICIT_VIDEO_REQUESTS.some(pattern => pattern.test(text))
}

/**
 * The LLM remains the planner, but an unmistakable user command must not turn
 * into a clarification loop. Repair that one high-value intent locally with
 * conservative defaults. This is deliberately narrow: questions such as
 * “how do I generate a video?” and negated requests remain read-only.
 */
export function reconcileAgentTurnWithRequest(request: string, turn: AgentTurn): AgentTurn {
  if (!isExplicitVideoGenerationRequest(request)) return turn

  const navigation = turn.actions
    .filter((action): action is AgentOpenTabAction => action.type === 'open_tab')
    .slice(0, MAX_ACTIONS - 2)
  const prepare = turn.actions.find(
    (action): action is AgentPrepareVideoAction => action.type === 'prepare_video',
  ) || {
      type: 'prepare_video',
      prompt: request.trim().slice(0, 8_000),
      durationSeconds: 5,
      resolutionPreset: '720p',
      aspectRatio: '16:9',
      seed: -1,
      outputCount: 1,
    } satisfies AgentPrepareVideoAction

  return {
    reply: '¡La petición está clara! Usaré un conjuro de vídeo estándar con los ajustes disponibles, prepararé Studio → Video y lo enviaré a la cola. 🪄',
    actions: [...navigation, prepare, { type: 'start_generation' }],
  }
}

export const HOCUSPOCUS_AGENT_RESPONSE_SCHEMA: Record<string, unknown> = {
  type: 'object',
  additionalProperties: false,
  properties: {
    reply: { type: 'string', maxLength: 8_000 },
    actions: {
      type: 'array',
      maxItems: MAX_ACTIONS,
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          type: { type: 'string', enum: ['open_tab', 'prepare_video', 'start_generation'] },
          tab: { type: 'string', enum: ['', ...AGENT_TABS] },
          prompt: { type: 'string', maxLength: 8_000 },
          model_type: { type: 'string', maxLength: 160 },
          duration_seconds: { type: 'number', minimum: 0, maximum: 300 },
          resolution_preset: { type: 'string', enum: ['', 'auto', '480p', '540p', '720p', '768p', '1080p'] },
          resolution: { type: 'string', maxLength: 20 },
          aspect_ratio: { type: 'string', enum: ['', 'auto', '21:9', '16:9', '9:16', '1:1', '4:3', '3:4'] },
          negative_prompt: { type: 'string', maxLength: 2_000 },
          seed: { type: 'integer', minimum: -1, maximum: 2_147_483_647 },
          inference_steps: { type: 'integer', minimum: 0, maximum: 100 },
          guidance_scale: { type: 'number', minimum: -1, maximum: 30 },
          output_count: { type: 'integer', minimum: 0, maximum: 8 },
          audio_direction: { type: 'string', maxLength: 1_000 },
          turbo: { type: 'string', enum: ['keep', 'on', 'off'] },
        },
        required: [
          'type', 'tab', 'prompt', 'model_type', 'duration_seconds',
          'resolution_preset', 'resolution', 'aspect_ratio', 'negative_prompt',
          'seed', 'inference_steps', 'guidance_scale', 'output_count',
          'audio_direction', 'turbo',
        ],
      },
    },
  },
  required: ['reply', 'actions'],
}

export function buildAgentAppSnapshot(): AgentAppSnapshot {
  const state = useStore.getState()
  return {
    current: {
      media_filter: state.mediaFilter,
      sidebar_mode: state.sidebarMode,
      sidebar_open: state.sidebarOpen,
      generation_mode: state.generationMode,
      selected_model: state.params.model_type,
      prompt_preview: String(state.params.prompt || '').slice(0, 500),
      duration_seconds: state.durationSeconds,
      resolution: state.params.resolution,
      aspect_ratio: state.aspectRatio,
    },
    available_video_models: state.models
      .filter(model => model.is_t2v && !model.tool_only)
      .slice(0, 80)
      .map(model => ({
        model_type: model.model_type,
        name: model.name,
        family: model.family,
        installed: model.is_downloaded === true,
        enabled: state.enabledModels.has(model.model_type),
        text_to_video: model.is_t2v,
      })),
  }
}

const TAB_TARGETS: Partial<Record<AgentTab, MediaFilter>> = {
  images: 'images',
  videos: 'videos',
  audio: 'audio',
  '3d': 'model3d',
  story_lab: 'stories',
  series_lab: 'series',
  comics: 'comics',
  video_editor: 'videoeditor',
  video_3d: 'scene3d',
  animate_3d: 'animate3d',
  character_creator: 'characters',
  character_kit: 'characters',
  workspaces: 'workspaces',
}

const TAB_LABELS: Record<AgentTab, string> = {
  studio: 'Studio',
  director: 'Director',
  productions: 'Productions',
  images: 'Images',
  videos: 'Videos',
  audio: 'Audio',
  '3d': '3D',
  story_lab: 'Story Lab',
  series_lab: 'Series Lab',
  comics: 'Comics',
  video_editor: 'Video Editor',
  video_3d: '3D Video',
  animate_3d: 'Animate 3D',
  character_creator: 'Character Creator',
  character_kit: 'CharacterKit',
  workspaces: 'Workspaces',
  settings: 'Settings',
}

function openTab(tab: AgentTab): string {
  const state = useStore.getState()
  const overlayWasVisible = state.settingsOpen || state.dashboardOpen
  const mobile = window.matchMedia('(max-width: 767px)').matches
  const sidebarWasVisible = !mobile || state.sidebarOpen
  if (tab === 'settings') {
    const alreadyVisible = state.settingsOpen
    state.setDashboardOpen(false)
    state.setSidebarOpen(false)
    state.setSettingsOpen(true)
    return alreadyVisible ? `${TAB_LABELS[tab]} ya estaba visible.` : `He abierto ${TAB_LABELS[tab]}.`
  }
  state.setSettingsOpen(false)
  if (tab === 'productions') {
    const alreadyVisible = state.dashboardOpen
    state.setSidebarOpen(false)
    state.setDashboardOpen(true)
    return alreadyVisible ? `${TAB_LABELS[tab]} ya estaba visible.` : `He abierto ${TAB_LABELS[tab]}.`
  }
  state.setDashboardOpen(false)
  if (tab === 'director') {
    const directorWasCollapsed = window.localStorage.getItem('maestro-director-sidebar-collapsed') === 'true'
    const alreadyVisible = state.sidebarMode === 'director'
      && sidebarWasVisible
      && !directorWasCollapsed
      && !overlayWasVisible
    state.setSidebarMode('director')
    state.setSidebarOpen(true)
    window.dispatchEvent(new Event('maestro:director-open'))
    return alreadyVisible ? `${TAB_LABELS[tab]} ya estaba visible.` : `He abierto ${TAB_LABELS[tab]}.`
  } else if (tab === 'studio') {
    const alreadyVisible = state.sidebarMode === 'studio' && sidebarWasVisible && !overlayWasVisible
    state.setSidebarMode('studio')
    state.setSidebarOpen(true)
    return alreadyVisible ? `${TAB_LABELS[tab]} ya estaba visible.` : `He abierto ${TAB_LABELS[tab]}.`
  } else {
    const mediaFilter = TAB_TARGETS[tab]
    const alreadyVisible = mediaFilter === state.mediaFilter && !overlayWasVisible
    if (mediaFilter) {
      state.setMediaFilter(mediaFilter)
      state.setSidebarOpen(false)
    }
    return alreadyVisible ? `${TAB_LABELS[tab]} ya estaba visible.` : `He abierto ${TAB_LABELS[tab]}.`
  }
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

async function prepareVideo(action: AgentPrepareVideoAction): Promise<string> {
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

  return `He preparado Studio → Video con ${selected.name}, ${useStore.getState().durationSeconds.toFixed(1)} s y el prompt indicado.`
}

async function startPreparedGeneration(): Promise<string> {
  const before = useStore.getState().jobs
  const knownJobs = new Set(before)
  await useStore.getState().startGeneration()
  const created = useStore.getState().jobs.find(job => !knownJobs.has(job))
  if (!created) throw new Error('HocusPocus no creó una tarea; revisa los requisitos del modelo y los campos visibles.')
  if (created.status === 'failed') throw new Error(created.error || created.message || 'La generación no pudo entrar en cola.')
  return created.id
    ? `He enviado el vídeo a la cola (${created.id}).`
    : 'He enviado el vídeo a la cola; HocusPocus está asignando su identificador.'
}

export async function executeAgentActions(
  actions: AgentAction[],
  onStep?: (message: string) => void,
): Promise<AgentActionResult[]> {
  const results: AgentActionResult[] = []
  let preparedVideo = false
  for (const action of actions) {
    const working = action.type === 'open_tab'
      ? `Abriendo ${TAB_LABELS[action.tab]}…`
      : action.type === 'prepare_video'
        ? 'Trazando el hechizo de vídeo en Studio…'
        : 'Enviando el vídeo a la cola…'
    onStep?.(working)
    try {
      if (action.type === 'open_tab') {
        results.push({ action, ok: true, message: openTab(action.tab) })
      } else if (action.type === 'prepare_video') {
        const message = await prepareVideo(action)
        preparedVideo = true
        results.push({ action, ok: true, message })
      } else {
        if (!preparedVideo) throw new Error('El vídeo no se preparó en este turno; no lo he lanzado.')
        results.push({ action, ok: true, message: await startPreparedGeneration() })
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      results.push({ action, ok: false, message })
      if (action.type === 'prepare_video') preparedVideo = false
    }
  }
  return results
}
