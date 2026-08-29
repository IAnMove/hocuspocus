import { getModelsForFamily, getFamiliesForMode, useStore } from '../../stores/useStore'
import type { AspectRatio, MediaFilter, ModelDef, ResolutionPreset } from '../../types'
import type { AgentSeriesSection, AgentStorySection } from './agentUiBus'
import { ARCADE_HORDE_SFX_PACK, type AgentSfxClip } from './sfxPack'

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

export interface AgentPrepareImageAction {
  type: 'prepare_image'
  prompt: string
  modelType?: string
  resolutionPreset?: ResolutionPreset
  resolution?: string
  aspectRatio?: AspectRatio
  negativePrompt?: string
  seed?: number
  inferenceSteps?: number
  guidanceScale?: number
  outputCount?: number
}

export interface AgentPrepareAudioAction {
  type: 'prepare_audio'
  subMode: 'speech' | 'music' | 'sfx'
  prompt: string
  modelType?: string
  durationSeconds?: number
  negativePrompt?: string
}

export interface AgentQueueSfxPackAction {
  type: 'queue_sfx_pack'
  style: string
  clips: AgentSfxClip[]
  modelType?: string
  negativePrompt?: string
  confirm: true
}

export interface AgentStartGenerationAction {
  type: 'start_generation'
}

export interface AgentOpenStorySectionAction {
  type: 'open_story_section'
  section: AgentStorySection
}

export interface AgentOpenSeriesSectionAction {
  type: 'open_series_section'
  section: AgentSeriesSection
}

export interface AgentCreativeCharacter {
  name: string
  role: string
  personality: string
  desire: string
  flaw: string
  appearance: string
  voice: string
}

export interface AgentCreativeLocation {
  name: string
  purpose: string
  description: string
}

export interface AgentCreateStoryAction {
  type: 'create_story'
  title: string
  projectType: 'full_story' | 'music_video' | 'trailer' | 'quick_video'
  creativeBrief: string
  premise: string
  logline: string
  synopsis: string
  theme: string
  ending: string
  genre: string
  tone: string
  visualStyle: string
  worldSummary: string
  language: string
  characters: AgentCreativeCharacter[]
  locations: AgentCreativeLocation[]
  outlineBeats: string[]
  durationSeconds?: number
}

export interface AgentCreateSeriesEpisodeAction {
  type: 'create_series_episode'
  seriesTitle: string
  seriesPremise: string
  seriesLogline: string
  episodeTitle: string
  episodePremise: string
  episodeLogline: string
  genre: string
  tone: string
  visualStyle: string
  worldSummary: string
  theme: string
  ending: string
  language: string
  characters: AgentCreativeCharacter[]
  locations: AgentCreativeLocation[]
  outlineBeats: string[]
  targetDurationSeconds?: number
  createIfMissing: boolean
  knownUniverse: boolean
}

export interface AgentInspectQueueAction {
  type: 'inspect_queue'
  scope: 'active' | 'all'
}

export interface AgentCancelTaskAction {
  type: 'cancel_task'
  taskId: string
  confirm: true
}

export interface AgentResumeTaskAction {
  type: 'resume_task'
  taskId: string
  confirm: true
}

export type AgentAction = AgentOpenTabAction
  | AgentOpenStorySectionAction
  | AgentOpenSeriesSectionAction
  | AgentPrepareVideoAction
  | AgentPrepareImageAction
  | AgentPrepareAudioAction
  | AgentQueueSfxPackAction
  | AgentStartGenerationAction
  | AgentCreateStoryAction
  | AgentCreateSeriesEpisodeAction
  | AgentInspectQueueAction
  | AgentCancelTaskAction
  | AgentResumeTaskAction

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
  available_image_models: Array<{
    model_type: string
    name: string
    family: string
    installed: boolean
    enabled: boolean
  }>
}

const TAB_SET = new Set<string>(AGENT_TABS)
const RESOLUTION_PRESETS = new Set<ResolutionPreset>(['auto', '480p', '540p', '720p', '768p', '1080p'])
const ASPECT_RATIOS = new Set<AspectRatio>(['auto', '21:9', '16:9', '9:16', '1:1', '4:3', '3:4'])
const STORY_PROJECT_TYPES = new Set<AgentCreateStoryAction['projectType']>([
  'full_story', 'music_video', 'trailer', 'quick_video',
])
const STORY_SECTIONS = new Set<AgentStorySection>([
  'overview', 'world', 'characters', 'relationships', 'structure', 'productions',
])
const SERIES_SECTIONS = new Set<AgentSeriesSection>([
  'setup', 'canon', 'episode', 'shots', 'review',
])
const MAX_ACTIONS = 6
const AUDIO_SUB_MODES = new Set<AgentPrepareAudioAction['subMode']>(['speech', 'music', 'sfx'])
const ACTION_TYPE_ALIASES: Record<string, AgentAction['type']> = {
  opentab: 'open_tab',
  openstorysection: 'open_story_section',
  openseriessection: 'open_series_section',
  preparevideo: 'prepare_video',
  prepareimage: 'prepare_image',
  prepareaudio: 'prepare_audio',
  queuesfxpack: 'queue_sfx_pack',
  startgeneration: 'start_generation',
  createstory: 'create_story',
  createseriesepisode: 'create_series_episode',
  inspectqueue: 'inspect_queue',
  canceltask: 'cancel_task',
  resumetask: 'resume_task',
}

const cleanString = (value: unknown, maxLength: number): string => (
  typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
)

function canonicalActionType(value: unknown): string {
  const raw = cleanString(value, 40)
  const collapsed = raw.toLowerCase().replace(/[^a-z0-9]/g, '')
  return ACTION_TYPE_ALIASES[collapsed] || raw
}

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

const stringArray = (value: unknown, maxItems: number, maxLength: number): string[] => (
  Array.isArray(value)
    ? value.slice(0, maxItems).flatMap(item => {
      const text = cleanString(item, maxLength)
      return text ? [text] : []
    })
    : []
)

const creativeCharacters = (value: unknown): AgentCreativeCharacter[] => (
  Array.isArray(value) ? value.slice(0, 16).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const name = cleanString(raw.name, 160)
    if (!name) return []
    return [{
      name,
      role: cleanString(raw.role, 300),
      personality: cleanString(raw.personality, 1_000),
      desire: cleanString(raw.desire, 1_000),
      flaw: cleanString(raw.flaw, 1_000),
      appearance: cleanString(raw.appearance, 1_000),
      voice: cleanString(raw.voice, 1_000),
    }]
  }) : []
)

const creativeLocations = (value: unknown): AgentCreativeLocation[] => (
  Array.isArray(value) ? value.slice(0, 16).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const name = cleanString(raw.name, 160)
    if (!name) return []
    return [{
      name,
      purpose: cleanString(raw.purpose, 1_000),
      description: cleanString(raw.description, 1_500),
    }]
  }) : []
)

const extractJsonObject = (raw: string): Record<string, unknown> | null => {
  const trimmed = raw.trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, '')
  const start = trimmed.indexOf('{')
  if (start < 0) return null
  for (let end = trimmed.lastIndexOf('}'); end > start; end = trimmed.lastIndexOf('}', end - 1)) {
    try {
      const parsed = JSON.parse(trimmed.slice(start, end + 1))
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, unknown>
      }
    } catch {
      continue
    }
  }
  return null
}

const CANONICAL_FIELD_NAMES = [
  'type', 'tab', 'story_section', 'series_section', 'prompt', 'model_type',
  'duration_seconds', 'resolution_preset', 'resolution', 'aspect_ratio',
  'negative_prompt', 'seed', 'inference_steps', 'guidance_scale', 'output_count',
  'audio_direction', 'turbo', 'title', 'project_type', 'creative_brief',
  'premise', 'logline', 'synopsis', 'theme', 'ending', 'genre', 'tone',
  'visual_style', 'world_summary', 'language', 'series_title', 'series_premise',
  'series_logline', 'episode_title', 'episode_premise', 'episode_logline',
  'target_duration_seconds', 'create_if_missing', 'known_universe',
  'queue_scope', 'task_id', 'confirm', 'characters', 'locations', 'outline_beats',
  'audio_sub_mode', 'sfx_clips', 'name', 'actions', 'reply',
] as const

function collapsedKey(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, '')
}

export function humanReply(raw: string): string {
  const object = extractJsonObject(raw)
  if (typeof object?.reply === 'string' && object.reply.trim()) return object.reply.trim()
  const quoted = raw.match(/"reply"\s*:\s*"((?:\\.|[^"\\])*)"/)
  if (quoted) {
    try {
      return JSON.parse(`"${quoted[1]}"`)
    } catch {
      return quoted[1].replace(/\\n/g, '\n')
    }
  }
  return raw.trim()
}

function canonicalRecord(raw: Record<string, unknown>): Record<string, unknown> {
  const collapsed = new Map<string, unknown>()
  for (const [key, value] of Object.entries(raw)) collapsed.set(collapsedKey(key), value)
  const next: Record<string, unknown> = { ...raw }
  for (const name of CANONICAL_FIELD_NAMES) {
    if (next[name] === undefined) {
      const hit = collapsed.get(collapsedKey(name))
      if (hit !== undefined) next[name] = hit
    }
  }
  if (Array.isArray(next.sfx_clips)) {
    next.sfx_clips = next.sfx_clips.map(item => (
      item && typeof item === 'object' && !Array.isArray(item)
        ? canonicalRecord(item as Record<string, unknown>)
        : item
    ))
  }
  return next
}

function parseSfxClips(value: unknown): AgentSfxClip[] {
  return Array.isArray(value) ? value.slice(0, 12).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const name = cleanString(raw.name, 80)
    const prompt = cleanString(raw.prompt, 1_500)
    if (!name || !prompt) return []
    return [{
      name,
      prompt,
      durationSeconds: optionalPositiveNumber(raw.duration_seconds, 1, 20) ?? 1,
    }]
  }) : []
}

function parseAction(value: unknown): AgentAction | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = canonicalRecord(value as Record<string, unknown>)
  const type = canonicalActionType(raw.type)
  if (type === 'open_tab') {
    const tab = cleanString(raw.tab, 40)
    return TAB_SET.has(tab) ? { type: 'open_tab', tab: tab as AgentTab } : null
  }
  if (type === 'open_story_section') {
    const section = cleanString(raw.story_section, 40) as AgentStorySection
    return STORY_SECTIONS.has(section) ? { type: 'open_story_section', section } : null
  }
  if (type === 'open_series_section') {
    const section = cleanString(raw.series_section, 40) as AgentSeriesSection
    return SERIES_SECTIONS.has(section) ? { type: 'open_series_section', section } : null
  }
  if (type === 'prepare_video') {
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
  if (type === 'prepare_image') {
    const prompt = cleanString(raw.prompt, 8_000)
    if (!prompt) return null
    const resolutionPreset = cleanString(raw.resolution_preset, 12) as ResolutionPreset
    const aspectRatio = cleanString(raw.aspect_ratio, 12) as AspectRatio
    const resolution = cleanString(raw.resolution, 20)
    return {
      type: 'prepare_image',
      prompt,
      modelType: cleanString(raw.model_type, 160) || undefined,
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
    }
  }
  if (type === 'prepare_audio') {
    const prompt = cleanString(raw.prompt, 8_000)
    if (!prompt) return null
    const subMode = cleanString(raw.audio_sub_mode, 12) as AgentPrepareAudioAction['subMode']
    return {
      type: 'prepare_audio',
      subMode: AUDIO_SUB_MODES.has(subMode) ? subMode : 'sfx',
      prompt,
      modelType: cleanString(raw.model_type, 160) || undefined,
      durationSeconds: optionalPositiveNumber(raw.duration_seconds, 1, 20),
      negativePrompt: cleanString(raw.negative_prompt, 2_000) || undefined,
    }
  }
  if (type === 'queue_sfx_pack') {
    if (raw.confirm !== true) return null
    const clips = parseSfxClips(raw.sfx_clips)
    if (!clips.length) return null
    return {
      type: 'queue_sfx_pack',
      style: cleanString(raw.visual_style, 2_000) || cleanString(raw.theme, 1_000),
      clips,
      modelType: cleanString(raw.model_type, 160) || undefined,
      negativePrompt: cleanString(raw.negative_prompt, 2_000) || undefined,
      confirm: true,
    }
  }
  if (type === 'start_generation') return { type: 'start_generation' }
  if (type === 'create_story') {
    const title = cleanString(raw.title, 300)
    const premise = cleanString(raw.premise, 2_000)
    if (!title || !premise) return null
    const projectType = cleanString(raw.project_type, 30) as AgentCreateStoryAction['projectType']
    return {
      type: 'create_story',
      title,
      projectType: STORY_PROJECT_TYPES.has(projectType) ? projectType : 'full_story',
      creativeBrief: cleanString(raw.creative_brief, 4_000),
      premise,
      logline: cleanString(raw.logline, 2_000),
      synopsis: cleanString(raw.synopsis, 6_000),
      theme: cleanString(raw.theme, 1_000),
      ending: cleanString(raw.ending, 2_000),
      genre: cleanString(raw.genre, 300),
      tone: cleanString(raw.tone, 500),
      visualStyle: cleanString(raw.visual_style, 2_000),
      worldSummary: cleanString(raw.world_summary, 3_000),
      language: cleanString(raw.language, 120),
      characters: creativeCharacters(raw.characters),
      locations: creativeLocations(raw.locations),
      outlineBeats: stringArray(raw.outline_beats, 24, 1_500),
      durationSeconds: optionalPositiveNumber(raw.target_duration_seconds, 15, 3_600, true),
    }
  }
  if (type === 'create_series_episode') {
    const seriesTitle = cleanString(raw.series_title, 300)
    const episodePremise = cleanString(raw.episode_premise, 3_000)
    if (!seriesTitle || !episodePremise) return null
    return {
      type: 'create_series_episode',
      seriesTitle,
      seriesPremise: cleanString(raw.series_premise, 3_000),
      seriesLogline: cleanString(raw.series_logline, 2_000),
      episodeTitle: cleanString(raw.episode_title, 300),
      episodePremise,
      episodeLogline: cleanString(raw.episode_logline, 2_000),
      genre: cleanString(raw.genre, 300),
      tone: cleanString(raw.tone, 500),
      visualStyle: cleanString(raw.visual_style, 2_000),
      worldSummary: cleanString(raw.world_summary, 3_000),
      theme: cleanString(raw.theme, 1_000),
      ending: cleanString(raw.ending, 2_000),
      language: cleanString(raw.language, 120),
      characters: creativeCharacters(raw.characters),
      locations: creativeLocations(raw.locations),
      outlineBeats: stringArray(raw.outline_beats, 24, 1_500),
      targetDurationSeconds: optionalPositiveNumber(raw.target_duration_seconds, 15, 3_600, true),
      createIfMissing: raw.create_if_missing === true,
      knownUniverse: raw.known_universe === true,
    }
  }
  if (type === 'inspect_queue') {
    const scope = cleanString(raw.queue_scope, 12)
    return { type: 'inspect_queue', scope: scope === 'all' ? 'all' : 'active' }
  }
  if (type === 'cancel_task') {
    if (raw.confirm !== true) return null
    return { type: 'cancel_task', taskId: cleanString(raw.task_id, 160), confirm: true }
  }
  if (type === 'resume_task') {
    if (raw.confirm !== true) return null
    return { type: 'resume_task', taskId: cleanString(raw.task_id, 160), confirm: true }
  }
  return null
}

/**
 * Treat model output as an untrusted proposal. Only known actions and bounded
 * fields survive, and generation can start only after this same turn prepared
 * a Studio form. That prevents stale chat context from firing the current form.
 */
export function parseAgentTurn(raw: string): AgentTurn {
  const object = extractJsonObject(raw)
  if (!object) return { reply: humanReply(raw.trim()), actions: [] }
  let reply = cleanString(object.reply, 8_000)
  if (reply.startsWith('{')) {
    const nested = extractJsonObject(reply)
    if (typeof nested?.reply === 'string') reply = cleanString(nested.reply, 8_000)
  }
  const proposed = Array.isArray(object.actions) ? object.actions.slice(0, MAX_ACTIONS) : []
  const actions: AgentAction[] = []
  let preparedStudio = false
  let startedGeneration = false
  for (const value of proposed) {
    const action = parseAction(value)
    if (!action) continue
    if (action.type === 'prepare_video' || action.type === 'prepare_image' || action.type === 'prepare_audio') preparedStudio = true
    if (action.type === 'start_generation') {
      if (!preparedStudio || startedGeneration) continue
      startedGeneration = true
    }
    actions.push(action)
  }
  return {
    reply: reply || (actions.length ? 'El hechizo está trazado; voy a mover HocusPocus.' : humanReply(raw.trim())),
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

const EXPLICIT_CANCEL_REQUESTS = [
  /\b(?:cancela|cancelad|cancelar|para|parad|det[eé]n|detened)\b[^.!?\n]*\b(?:tarea|trabajo|job|cola|generaci[oó]n|v[ií]deo|video|clip)\b/i,
  /\b(?:para|parad|det[eé]n)\b[^.!?\n]*\b(?:lo que est[aá] (?:generando|renderizando|en cola|corriendo))\b/i,
  /\b(?:cancel|stop|abort)\b[^.!?\n]*\b(?:task|job|queue|generation|video|clip|active)\b/i,
]
const NEGATED_CANCEL_REQUEST = /\b(?:no|sin|don['’]?t|do\s+not)\b[^.!?\n]{0,24}\b(?:cancel|cancela|canceles|pares|detengas|stop|abort)\b/i

export function isExplicitCancelRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_CANCEL_REQUEST.test(text)) return false
  return EXPLICIT_CANCEL_REQUESTS.some(pattern => pattern.test(text))
}

export function isExplicitVideoGenerationRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text)) return false
  return EXPLICIT_VIDEO_REQUESTS.some(pattern => pattern.test(text))
}

const EXPLICIT_IMAGE_REQUESTS = [
  /\b(?:hazme|hacedme|generame|genérame|creame|créame)\b[^.!?\n]*\b(?:imagen|im[aá]genes|foto|fotos|retrato|ilustraci[oó]n)\b/i,
  /\b(?:haz|haced|genera|generad|crea|cread|lanza|lanzad|encola|encolad)\b[^.!?\n]*\b(?:imagen|im[aá]genes|foto|fotos|retrato|ilustraci[oó]n)\b/i,
  /\b(?:quiero|quisiera)\s+que\s+(?:me\s+)?(?:hagas|generes|crees|lances)\b[^.!?\n]*\b(?:imagen|foto|retrato)\b/i,
  /\b(?:make|create|generate|render|queue)\b[^.!?\n]*\b(?:image|picture|photo|portrait|illustration)\b/i,
]

export function isExplicitImageGenerationRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text)) return false
  if (isExplicitVideoGenerationRequest(text)) return false
  return EXPLICIT_IMAGE_REQUESTS.some(pattern => pattern.test(text))
}

const EXPLICIT_SFX_REQUESTS = [
  /\b(?:efectos?(?:\s+de\s+sonido)?|sfx|sound effects?|sonidos?)\b/i,
]
const EXPLICIT_SFX_GENERATE = [
  /\b(?:genera(?:r|d|me)?|crea(?:r|d|me|ndo)?|hazme|hacedme|lanza(?:r|d)?|encola(?:r|d)?|make|creat(?:e|ing)|generat(?:e|ing)|queue)\b/i,
]
const GAME_SFX_HINT = /\b(?:vampire\s*survivors|oleadas?|horde|twin[\s-]?stick|arcade|juego|game)\b/i

export function isExplicitSfxGenerationRequest(request: string): boolean {
  const text = request.trim()
  if (!text || NEGATED_VIDEO_REQUEST.test(text)) return false
  return EXPLICIT_SFX_REQUESTS.some(pattern => pattern.test(text))
    && EXPLICIT_SFX_GENERATE.some(pattern => pattern.test(text))
}

/**
 * The LLM remains the planner, but an unmistakable user command must not turn
 * into a clarification loop. Repair that one high-value intent locally with
 * conservative defaults. This is deliberately narrow: questions such as
 * “how do I generate a video?” and negated requests remain read-only.
 */
export function reconcileAgentTurnWithRequest(request: string, turn: AgentTurn): AgentTurn {
  if (isExplicitSfxGenerationRequest(request)) {
    const existing = turn.actions.find(
      (action): action is AgentQueueSfxPackAction => action.type === 'queue_sfx_pack',
    )
    const clips = existing?.clips.length
      ? existing.clips
      : GAME_SFX_HINT.test(request) ? ARCADE_HORDE_SFX_PACK : []
    if (clips.length) {
      return {
        reply: 'Prepararé Studio → Audio → SFX y encolaré el pack de efectos. Irán detrás de lo que ya use la GPU. La galería Audios solo muestra resultados cuando terminen. 🪄',
        actions: [{
          type: 'queue_sfx_pack',
          style: existing?.style || 'retro fantasy arcade',
          clips,
          confirm: true,
        }],
      }
    }
  }
  if (isExplicitCancelRequest(request)) {
    const existing = turn.actions.find(
      (action): action is AgentCancelTaskAction => action.type === 'cancel_task',
    )
    return {
      reply: 'Cancelaré la tarea activa en la cola canónica y dejaré Activity a la vista. 🪄',
      actions: [{ type: 'cancel_task', taskId: existing?.taskId || '', confirm: true }],
    }
  }
  if (isExplicitVideoGenerationRequest(request)) {
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
  if (!isExplicitImageGenerationRequest(request)) return turn

  const navigation = turn.actions
    .filter((action): action is AgentOpenTabAction => action.type === 'open_tab')
    .slice(0, MAX_ACTIONS - 2)
  const prepare = turn.actions.find(
    (action): action is AgentPrepareImageAction => action.type === 'prepare_image',
  ) || {
      type: 'prepare_image',
      prompt: request.trim().slice(0, 8_000),
      resolutionPreset: 'auto',
      aspectRatio: 'auto',
      seed: -1,
      outputCount: 1,
    } satisfies AgentPrepareImageAction

  return {
    reply: '¡La petición está clara! Prepararé Studio → Image con un modelo compatible y lo enviaré a la cola. 🪄',
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
          type: { type: 'string', enum: ['open_tab', 'open_story_section', 'open_series_section', 'prepare_video', 'prepare_image', 'prepare_audio', 'queue_sfx_pack', 'start_generation', 'create_story', 'create_series_episode', 'inspect_queue', 'cancel_task', 'resume_task'] },
          tab: { type: 'string', enum: ['', ...AGENT_TABS] },
          story_section: { type: 'string', enum: ['', ...STORY_SECTIONS] },
          series_section: { type: 'string', enum: ['', ...SERIES_SECTIONS] },
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
          title: { type: 'string', maxLength: 300 },
          project_type: { type: 'string', enum: ['', 'full_story', 'music_video', 'trailer', 'quick_video'] },
          creative_brief: { type: 'string', maxLength: 4_000 },
          premise: { type: 'string', maxLength: 2_000 },
          logline: { type: 'string', maxLength: 2_000 },
          synopsis: { type: 'string', maxLength: 6_000 },
          theme: { type: 'string', maxLength: 1_000 },
          ending: { type: 'string', maxLength: 2_000 },
          genre: { type: 'string', maxLength: 300 },
          tone: { type: 'string', maxLength: 500 },
          visual_style: { type: 'string', maxLength: 2_000 },
          world_summary: { type: 'string', maxLength: 3_000 },
          language: { type: 'string', maxLength: 120 },
          series_title: { type: 'string', maxLength: 300 },
          series_premise: { type: 'string', maxLength: 3_000 },
          series_logline: { type: 'string', maxLength: 2_000 },
          episode_title: { type: 'string', maxLength: 300 },
          episode_premise: { type: 'string', maxLength: 3_000 },
          episode_logline: { type: 'string', maxLength: 2_000 },
          target_duration_seconds: { type: 'number', minimum: 0, maximum: 3_600 },
          create_if_missing: { type: 'boolean' },
          known_universe: { type: 'boolean' },
          queue_scope: { type: 'string', enum: ['', 'active', 'all'] },
          task_id: { type: 'string', maxLength: 160 },
          confirm: { type: 'boolean' },
          audio_sub_mode: { type: 'string', enum: ['', 'speech', 'music', 'sfx'] },
          sfx_clips: {
            type: 'array', maxItems: 12,
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                name: { type: 'string', maxLength: 80 },
                prompt: { type: 'string', maxLength: 1_500 },
                duration_seconds: { type: 'number', minimum: 0, maximum: 20 },
              },
              required: ['name', 'prompt', 'duration_seconds'],
            },
          },
          characters: {
            type: 'array', maxItems: 16,
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                name: { type: 'string', maxLength: 160 },
                role: { type: 'string', maxLength: 300 },
                personality: { type: 'string', maxLength: 1_000 },
                desire: { type: 'string', maxLength: 1_000 },
                flaw: { type: 'string', maxLength: 1_000 },
                appearance: { type: 'string', maxLength: 1_000 },
                voice: { type: 'string', maxLength: 1_000 },
              },
              required: ['name', 'role', 'personality', 'desire', 'flaw', 'appearance', 'voice'],
            },
          },
          locations: {
            type: 'array', maxItems: 16,
            items: {
              type: 'object', additionalProperties: false,
              properties: {
                name: { type: 'string', maxLength: 160 },
                purpose: { type: 'string', maxLength: 1_000 },
                description: { type: 'string', maxLength: 1_500 },
              },
              required: ['name', 'purpose', 'description'],
            },
          },
          outline_beats: { type: 'array', maxItems: 24, items: { type: 'string', maxLength: 1_500 } },
        },
        required: ['type'],
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
    available_image_models: getFamiliesForMode('image', state.families)
      .flatMap(family => getModelsForFamily(family.id, state.models, 'image'))
      .filter(model => !model.tool_only)
      .slice(0, 80)
      .map(model => ({
        model_type: model.model_type,
        name: model.name,
        family: model.family,
        installed: model.is_downloaded === true,
        enabled: state.enabledModels.has(model.model_type),
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

async function prepareImage(action: AgentPrepareImageAction): Promise<string> {
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
  return `He preparado Studio → Image con ${selected.name}, ${resolution} y el prompt indicado.`
}

async function startPreparedGeneration(): Promise<string> {
  const before = useStore.getState().jobs
  const knownJobs = new Set(before)
  await useStore.getState().startGeneration()
  const created = useStore.getState().jobs.find(job => !knownJobs.has(job))
  if (!created) throw new Error('HocusPocus no creó una tarea; revisa los requisitos del modelo y los campos visibles.')
  if (created.status === 'failed') throw new Error(created.error || created.message || 'La generación no pudo entrar en cola.')
  const mode = useStore.getState().generationMode
  const kind = mode === 'image' ? 'imagen' : mode === 'audio' ? 'pista de audio' : 'vídeo'
  return created.id
    ? `He enviado la ${kind} a la cola (${created.id}).`
    : `He enviado la ${kind} a la cola; HocusPocus está asignando su identificador.`
}

export async function executeAgentActions(
  actions: AgentAction[],
  onStep?: (message: string) => void,
): Promise<AgentActionResult[]> {
  const results: AgentActionResult[] = []
  let preparedStudio = false
  for (const action of actions) {
    const working = action.type === 'open_tab'
      ? `Abriendo ${TAB_LABELS[action.tab]}…`
      : action.type === 'open_story_section'
        ? `Abriendo Story Lab → ${action.section}…`
        : action.type === 'open_series_section'
          ? `Abriendo Series Lab → ${action.section}…`
      : action.type === 'prepare_video'
        ? 'Trazando el hechizo de vídeo en Studio…'
        : action.type === 'prepare_image'
          ? 'Trazando el hechizo de imagen en Studio…'
        : action.type === 'prepare_audio'
          ? 'Trazando el hechizo de audio en Studio…'
        : action.type === 'queue_sfx_pack'
          ? 'Encolando el pack de efectos SFX…'
        : action.type === 'start_generation'
          ? 'Enviando a la cola…'
          : action.type === 'create_story'
            ? 'Escribiendo y guardando la nueva historia…'
            : action.type === 'create_series_episode'
              ? 'Preparando la serie y el nuevo episodio…'
              : action.type === 'inspect_queue'
                ? 'Consultando la cola canónica…'
                : action.type === 'cancel_task'
                  ? 'Cancelando la tarea en la cola…'
                  : 'Reanudando la tarea en la cola…'
    onStep?.(working)
    try {
      if (action.type === 'open_tab') {
        results.push({ action, ok: true, message: openTab(action.tab) })
      } else if (action.type === 'open_story_section') {
        openTab('story_lab')
        const { openAgentStorySection } = await import('./agentUiBus')
        openAgentStorySection(action.section)
        results.push({ action, ok: true, message: `He abierto Story Lab → ${action.section}.` })
      } else if (action.type === 'open_series_section') {
        openTab('series_lab')
        const { openAgentSeriesSection } = await import('./agentUiBus')
        openAgentSeriesSection(action.section)
        results.push({ action, ok: true, message: `He abierto Series Lab → ${action.section}.` })
      } else if (action.type === 'prepare_video') {
        const message = await prepareVideo(action)
        preparedStudio = true
        results.push({ action, ok: true, message })
      } else if (action.type === 'prepare_image') {
        const message = await prepareImage(action)
        preparedStudio = true
        results.push({ action, ok: true, message })
      } else if (action.type === 'prepare_audio') {
        const { prepareAudio } = await import('./audioActions')
        const message = await prepareAudio(action)
        preparedStudio = true
        results.push({ action, ok: true, message })
      } else if (action.type === 'queue_sfx_pack') {
        const { queueSfxPack } = await import('./audioActions')
        results.push({ action, ok: true, message: await queueSfxPack(action) })
      } else if (action.type === 'start_generation') {
        if (!preparedStudio) throw new Error('Studio no se preparó en este turno; no lo he lanzado.')
        results.push({ action, ok: true, message: await startPreparedGeneration() })
      } else if (action.type === 'create_story') {
        const { createFilledStory } = await import('./labActions')
        results.push({ action, ok: true, message: await createFilledStory(action) })
      } else if (action.type === 'create_series_episode') {
        const { createFilledSeriesEpisode } = await import('./labActions')
        results.push({ action, ok: true, message: await createFilledSeriesEpisode(action) })
      } else if (action.type === 'inspect_queue') {
        const { inspectCanonicalQueue } = await import('./queueActions')
        results.push({ action, ok: true, message: await inspectCanonicalQueue(action.scope) })
      } else if (action.type === 'cancel_task') {
        const { cancelCanonicalQueueTask } = await import('./queueActions')
        results.push({ action, ok: true, message: await cancelCanonicalQueueTask(action.taskId, action.confirm) })
      } else {
        const { resumeCanonicalQueueTask } = await import('./queueActions')
        results.push({ action, ok: true, message: await resumeCanonicalQueueTask(action.taskId, action.confirm) })
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      results.push({ action, ok: false, message })
      if (action.type === 'prepare_video' || action.type === 'prepare_image' || action.type === 'prepare_audio') preparedStudio = false
    }
  }
  return results
}
