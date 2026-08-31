import type {
  AgentAction,
  AgentApply3dRhythmAction,
  AgentCreateRhythmic3dVideoAction,
  AgentSceneWorkflowAction,
  AgentOpen3dSceneAction,
  AgentSave3dSceneAction,
  AgentExport3dSceneAction,
  AgentCreateComicAction,
  AgentGenerateComicAction,
  AgentStartDirectorProductionAction,
  AgentStageStoryVideoAction,
  AgentStageStoryMusicVideoAction,
  AgentOpenTabAction,
} from './agentActions'
import { useStore } from '../../stores/useStore'
import type { AgentExecutionReport } from './agentContract'
import type { AgentExecutionTarget } from './agentContract'
import { executionKey, executionReport } from './agentContract'
import type { WizardApplicationAdapters } from './applicationAdapters'

export const AGENT_TABS = [
  'studio', 'director', 'productions', 'images', 'videos', 'audio', '3d',
  'story_lab', 'series_lab', 'comics', 'video_editor', 'video_3d', 'animate_3d',
  'character_creator', 'character_kit', 'workspaces', 'settings',
] as const

export type AgentTab = typeof AGENT_TABS[number]
export type CapabilityRisk = 'read' | 'edit' | 'compute' | 'external_cost'
export type CapabilityConfirmation = 'none' | 'required'

export interface CapabilityPresentation {
  destination: AgentTab | 'action'
  anchors: string[]
  replay?: 'atomic'
}

export interface CapabilityExecutionOutcome {
  message: string
  report?: AgentExecutionReport
  target?: AgentExecutionTarget
  taskId?: string
  pipelineId?: string
  outputNames?: string[]
}

export interface CapabilityExecutionContext {
  adapters: WizardApplicationAdapters
}

export interface CapabilityDefinition<TAction extends AgentAction = AgentAction> {
  name: TAction['type']
  title: string
  description: string
  useWhen: string
  parameters: string[]
  inputSchema: Record<string, unknown>
  risk: CapabilityRisk
  confirmation: CapabilityConfirmation
  progress: string
  resolve(raw: Record<string, unknown>): TAction | null
  validate(action: TAction): string[]
  prepare(action: TAction, context: CapabilityExecutionContext): Promise<TAction>
  execute(action: TAction, context: CapabilityExecutionContext): Promise<CapabilityExecutionOutcome>
  correlate(action: TAction, outcome: CapabilityExecutionOutcome): AgentExecutionTarget | undefined
  track(
    action: TAction,
    outcome: CapabilityExecutionOutcome,
    context: CapabilityExecutionContext,
  ): Promise<CapabilityExecutionOutcome>
  report: {
    targetKind: string
    successState: 'prepared' | 'completed'
  }
  summarize(action: TAction, outcome: CapabilityExecutionOutcome): string
  presentation: CapabilityPresentation
}

const definitions = new Map<string, CapabilityDefinition>()

export function defineCapability<TAction extends AgentAction>(
  definition: CapabilityDefinition<TAction>,
): CapabilityDefinition<TAction> {
  if (definitions.has(definition.name)) throw new Error(`Duplicate capability: ${definition.name}`)
  definitions.set(definition.name, definition as CapabilityDefinition)
  return definition
}

function text(value: unknown, maxLength: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
}

function boundedNumber(value: unknown, minimum: number, maximum: number, fallback: number): number {
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? Math.min(maximum, Math.max(minimum, parsed)) : fallback
}

const tabSet = new Set<string>(AGENT_TABS)
const rhythmCueSources = new Set(['beats', 'downbeats'])
const rhythmProfiles = new Set(['pulse', 'bounce', 'peek', 'camera-punch'])

defineCapability<AgentOpenTabAction>({
  name: 'open_tab',
  title: 'Open an application section',
  description: 'Navigate to a real HocusPocus section through its store state.',
  useWhen: 'The user asks to go somewhere or opening a section materially helps the answer.',
  parameters: ['tab'],
  inputSchema: {
    type: 'object', additionalProperties: false,
    properties: {
      type: { const: 'open_tab' },
      tab: { type: 'string', enum: AGENT_TABS },
    },
    required: ['type', 'tab'],
  },
  risk: 'read',
  confirmation: 'none',
  progress: 'Abriendo una sección de HocusPocus…',
  resolve(raw) {
    const tab = text(raw.tab, 40)
    return tabSet.has(tab) ? { type: 'open_tab', tab: tab as AgentTab } : null
  },
  validate(action) {
    return tabSet.has(action.tab) ? [] : ['tab must identify a HocusPocus section']
  },
  async prepare(action) { return action },
  async execute(action, context) {
    return context.adapters.openTab(action.tab)
  },
  correlate(_action, outcome) { return outcome.target },
  async track(_action, outcome) { return outcome },
  report: { targetKind: 'application_section', successState: 'completed' },
  summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'action', anchors: [] },
})

defineCapability<AgentApply3dRhythmAction>({
  name: 'apply_3d_rhythm',
  title: 'Apply music rhythm to an editable 3D scene layer',
  description: 'Open Video 3D, attach an exact existing audio output when requested, analyze BPM/beats/downbeats and bake a pulse, bounce, peek or camera-punch profile into ordinary keyframes.',
  useWhen: 'The user explicitly asks a current scene layer or camera to react to music.',
  parameters: ['scene_name', 'layer_name', 'audio_output_name', 'cue_source', 'rhythm_profile', 'intensity', 'confirm'],
  inputSchema: {
    type: 'object', additionalProperties: false,
    properties: {
      type: { const: 'apply_3d_rhythm' },
      scene_name: { type: 'string', maxLength: 300 },
      layer_name: { type: 'string', maxLength: 300 },
      audio_output_name: { type: 'string', maxLength: 300 },
      cue_source: { type: 'string', enum: ['beats', 'downbeats'] },
      rhythm_profile: { type: 'string', enum: ['pulse', 'bounce', 'peek', 'camera-punch'] },
      intensity: { type: 'number', minimum: 0, maximum: 1 },
      confirm: { const: true },
    },
    required: ['type', 'cue_source', 'rhythm_profile', 'confirm'],
  },
  risk: 'compute',
  confirmation: 'required',
  progress: 'Analizando la canción y creando keyframes rítmicos…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const cueSource = text(raw.cue_source, 30)
    const profile = text(raw.rhythm_profile, 30)
    if (!rhythmCueSources.has(cueSource) || !rhythmProfiles.has(profile)) return null
    return {
      type: 'apply_3d_rhythm',
      sceneName: text(raw.scene_name, 300),
      layerName: text(raw.layer_name, 300),
      audioOutputName: text(raw.audio_output_name, 300),
      cueSource: cueSource as AgentApply3dRhythmAction['cueSource'],
      profile: profile as AgentApply3dRhythmAction['profile'],
      intensity: boundedNumber(raw.intensity, 0, 1, .65),
      confirm: true,
    }
  },
  validate(action) {
    const errors: string[] = []
    if (!rhythmCueSources.has(action.cueSource)) errors.push('cueSource is invalid')
    if (!rhythmProfiles.has(action.profile)) errors.push('profile is invalid')
    if (action.confirm !== true) errors.push('confirmation is required')
    return errors
  },
  async prepare(action) { return action },
  async execute(action, context) {
    return context.adapters.video3d.applyRhythm(action)
  },
  correlate(_action, outcome) { return outcome.target },
  async track(_action, outcome) { return outcome },
  report: { targetKind: 'video_3d_scene', successState: 'prepared' },
  summarize(_action, outcome) { return outcome.message },
  presentation: {
    destination: 'video_3d',
    anchors: ['scene', 'layer', 'audio', 'rhythm-profile', 'intensity'],
    replay: 'atomic',
  },
})

defineCapability<AgentCreateRhythmic3dVideoAction>({
  name: 'create_rhythmic_3d_video',
  title: 'Create a complete rhythm-driven 3D video',
  description: 'Generate or reuse an exact song, wait for its canonical task, build an editable 3D scene, analyze the audio once, bake beat choreography, save the scene and publish its MP4.',
  useWhen: 'The user asks for a complete 3D video that follows a song or MP3 automatically.',
  parameters: ['scene_name', 'prompt', 'audio_output_name', 'visual_output_name', 'layer_name', 'duration_seconds', 'cue_source', 'rhythm_profile', 'intensity', 'confirm'],
  inputSchema: {
    type: 'object', additionalProperties: false,
    properties: {
      type: { const: 'create_rhythmic_3d_video' },
      scene_name: { type: 'string', maxLength: 300 },
      prompt: { type: 'string', maxLength: 8_000 },
      audio_output_name: { type: 'string', maxLength: 300 },
      visual_output_name: { type: 'string', maxLength: 300 },
      layer_name: { type: 'string', maxLength: 300 },
      duration_seconds: { type: 'number', minimum: 1, maximum: 300 },
      cue_source: { type: 'string', enum: ['beats', 'downbeats'] },
      rhythm_profile: { type: 'string', enum: ['pulse', 'bounce', 'peek', 'camera-punch'] },
      intensity: { type: 'number', minimum: 0, maximum: 1 },
      confirm: { const: true },
    },
    required: ['type', 'scene_name', 'visual_output_name', 'confirm'],
  },
  risk: 'compute', confirmation: 'required',
  progress: 'Invocando la canción y el vídeo 3D al ritmo…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const sceneName = text(raw.scene_name, 300)
    const audioOutputName = text(raw.audio_output_name, 300)
    const musicPrompt = text(raw.prompt, 8_000)
    const visualOutputName = text(raw.visual_output_name, 300)
    const cueSource = text(raw.cue_source, 30) || 'beats'
    const profile = text(raw.rhythm_profile, 30) || 'pulse'
    if (!sceneName || !visualOutputName || (!audioOutputName && !musicPrompt)
      || !rhythmCueSources.has(cueSource) || !rhythmProfiles.has(profile)) return null
    return {
      type: 'create_rhythmic_3d_video', sceneName, musicPrompt, audioOutputName,
      visualOutputName, layerName: text(raw.layer_name, 300) || 'Beat subject',
      durationSeconds: boundedNumber(raw.duration_seconds, 1, 300, 10),
      cueSource: cueSource as AgentCreateRhythmic3dVideoAction['cueSource'],
      profile: profile as AgentCreateRhythmic3dVideoAction['profile'],
      intensity: boundedNumber(raw.intensity, 0, 1, .65), confirm: true,
    }
  },
  validate(action) {
    const errors: string[] = []
    if (!action.sceneName) errors.push('sceneName is required')
    if (!action.visualOutputName) errors.push('visualOutputName must identify an exact existing visual output')
    if (!action.audioOutputName && !action.musicPrompt) errors.push('musicPrompt or audioOutputName is required')
    if (action.confirm !== true) errors.push('confirmation is required')
    return errors
  },
  async prepare(action) { return action },
  async execute(action, context) {
    const { startRhythmic3dWorkflow } = await import('./rhythmic3dWorkflow')
    const workflow = await startRhythmic3dWorkflow(action, context.adapters)
    const step = workflow.steps[workflow.currentStep] ?? workflow.steps.at(-1)
    return {
      message: `He iniciado el hechizo duradero “${action.sceneName}” (${workflow.workflowId}).`,
      target: { kind: 'wizard_workflow', id: workflow.workflowId, title: action.sceneName },
      taskId: step?.taskId || undefined,
      outputNames: workflow.outputRefs,
    }
  },
  correlate(_action, outcome) { return outcome.target },
  async track(_action, outcome) { return outcome },
  report: { targetKind: 'wizard_workflow', successState: 'prepared' },
  summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'video_3d', anchors: ['scene', 'audio', 'layers', 'timeline'], replay: 'atomic' },
})

defineCapability<AgentCreateComicAction>({
  name: 'create_comic', title: 'Create a filled Comic Director project',
  description: 'Create a new editable one- or multi-page comic with its specified pages, panels, lettering and image provider; it does not render artwork.',
  useWhen: 'The user asks to create a filled comic or a new multi-page comic project.',
  parameters: ['title', 'synopsis', 'language', 'visual_style', 'characters', 'comic_pages', 'comic_panels', 'image_provider', 'model_type'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'create_comic' }, title: { type: 'string', maxLength: 300 } }, required: ['type', 'title'] },
  risk: 'edit', confirmation: 'none', progress: 'Montando el cómic editable…',
  resolve(raw) {
    const title = text(raw.title, 300)
    if (!title) return null
    const pages = Array.isArray(raw.comic_pages) ? raw.comic_pages.slice(0, 100).flatMap((page, pageIndex) => {
      if (!page || typeof page !== 'object') return []
      const value = page as Record<string, unknown>
      const panelValues = Array.isArray(value.panels) ? value.panels : Array.isArray(value.comic_panels) ? value.comic_panels : []
      const panels = panelValues.slice(0, 12).flatMap(panel => {
        if (!panel || typeof panel !== 'object') return []
        const item = panel as Record<string, unknown>
        return [{ caption: text(item.caption, 2_000), dialogue: text(item.dialogue, 2_000), sfx: text(item.sfx, 500), scene: text(item.scene, 4_000) }]
      })
      return panels.length ? [{ title: text(value.title, 300) || `Página ${pageIndex + 1}`, stage: text(value.stage, 2_000), panels }] : []
    }) : []
    const panels = Array.isArray(raw.comic_panels) ? raw.comic_panels.slice(0, 12).flatMap(panel => {
      if (!panel || typeof panel !== 'object') return []
      const item = panel as Record<string, unknown>
      return [{ caption: text(item.caption, 2_000), dialogue: text(item.dialogue, 2_000), sfx: text(item.sfx, 500), scene: text(item.scene, 4_000) }]
    }) : []
    const provider = text(raw.image_provider, 20)
    const characters = Array.isArray(raw.characters) ? raw.characters.slice(0, 40).flatMap(character => {
      if (!character || typeof character !== 'object') return []
      const value = character as Record<string, unknown>
      const name = text(value.name, 300)
      return name ? [{ name, role: text(value.role, 300), personality: text(value.personality, 1_000), desire: text(value.desire, 1_000), flaw: text(value.flaw, 1_000), appearance: text(value.appearance, 2_000), voice: text(value.voice, 1_000) }] : []
    }) : []
    return {
      type: 'create_comic', title, synopsis: text(raw.synopsis, 6_000) || text(raw.premise, 2_000), language: text(raw.language, 120), styleName: text(raw.visual_style, 2_000),
      characters, panels, pages, imageProvider: provider === 'minimax' || provider === 'maestro' ? provider : 'profile', imageModel: text(raw.model_type, 160), factualBiography: raw.factual_biography === true,
    }
  },
  validate(action) { return action.title ? [] : ['title is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.comic.create(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'comic', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'comics', anchors: ['project', 'pages', 'panels'], replay: 'atomic' },
})

defineCapability<AgentGenerateComicAction>({
  name: 'generate_comic', title: 'Render Comic Director artwork',
  description: 'Render the selected missing, failed or all panels of the open comic through its configured local or MiniMax provider.',
  useWhen: 'The user explicitly asks to draw, render or generate comic images.',
  parameters: ['image_provider', 'model_type', 'render_scope', 'page_numbers', 'pilot', 'biography_review', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'generate_comic' }, confirm: { const: true } }, required: ['type', 'confirm'] },
  risk: 'compute', confirmation: 'required', progress: 'Dibujando las viñetas del cómic…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const provider = text(raw.image_provider, 20)
    const scope = text(raw.render_scope, 20)
    const pages = Array.isArray(raw.page_numbers) ? raw.page_numbers.map(Number).filter(value => Number.isInteger(value) && value > 0).slice(0, 100) : []
    return { type: 'generate_comic', imageProvider: provider === 'minimax' || provider === 'maestro' ? provider : 'keep', imageModel: text(raw.model_type, 160), scope: scope === 'all' || scope === 'failed' ? scope : 'missing', pages, pilot: raw.pilot === true, biographyReview: raw.biography_review === true, confirm: true }
  },
  validate(action) { return action.confirm === true ? [] : ['confirmation is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.comic.generate(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'comic', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'comics', anchors: ['generate-all-images'], replay: 'atomic' },
})

defineCapability<AgentStartDirectorProductionAction>({
  name: 'start_director_production', title: 'Start a prepared Director production',
  description: 'Start only the exact Story/Director production prepared by the Wizard and return its real pipeline ID.',
  useWhen: 'The user explicitly asks to start or queue the prepared Story film, trailer or music video.',
  parameters: ['target_story_title', 'production_kind', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'start_director_production' }, target_story_title: { type: 'string' }, production_kind: { type: 'string', enum: ['film', 'trailer', 'music_video'] }, confirm: { const: true } }, required: ['type', 'confirm'] },
  risk: 'compute', confirmation: 'required', progress: 'Iniciando el pipeline real de Director…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const kind = text(raw.production_kind, 30)
    if (kind !== 'film' && kind !== 'trailer' && kind !== 'music_video') return null
    return { type: 'start_director_production', targetStoryTitle: text(raw.target_story_title, 300), kind, confirm: true }
  },
  validate(action) { return action.confirm === true ? [] : ['confirmation is required'] }, async prepare(action) { return action },
  async execute(action, context) {
    const outcome = await context.adapters.storyLab.startDirectorProduction(action)
    return { ...outcome, report: executionReport({ state: 'running', message: outcome.message, target: outcome.target, pipelineId: outcome.pipelineId, recoverable: false, executionKey: executionKey({ workspace: useStore.getState().activeWorkspace || 'default', type: action.type, targetId: outcome.target.id, params: action }) }) }
  }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'director_production', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'director', anchors: ['production', 'pipeline'], replay: 'atomic' },
})

defineCapability<AgentStageStoryVideoAction>({
  name: 'stage_story_video', title: 'Prepare a Story video in Director',
  description: 'Create and verify an exact Story film or trailer production in Director without starting compute.',
  useWhen: 'The user asks to prepare a Story film or trailer for later review or launch.',
  parameters: ['target_story_title', 'production_kind', 'direction', 'duration_seconds', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'stage_story_video' }, production_kind: { type: 'string', enum: ['film', 'trailer'] }, confirm: { const: true } }, required: ['type', 'production_kind', 'confirm'] },
  risk: 'edit', confirmation: 'required', progress: 'Preparando la producción de Story en Director…',
  resolve(raw) { const kind = text(raw.production_kind, 30); return raw.confirm === true && (kind === 'film' || kind === 'trailer') ? { type: 'stage_story_video', targetStoryTitle: text(raw.target_story_title, 300), kind, direction: text(raw.direction, 4_000), durationSeconds: raw.duration_seconds === undefined ? undefined : boundedNumber(raw.duration_seconds, 15, 3_600, 60), confirm: true } : null },
  validate(action) { return action.confirm === true ? [] : ['confirmation is required'] }, async prepare(action) { return action }, async execute(action, context) { return context.adapters.storyLab.stageVideo(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'director_production', successState: 'prepared' }, summarize(_action, outcome) { return outcome.message }, presentation: { destination: 'director', anchors: ['production'], replay: 'atomic' },
})

defineCapability<AgentStageStoryMusicVideoAction>({
  name: 'stage_story_music_video', title: 'Prepare a Story music video in Director',
  description: 'Resolve the exact Story song and cue, then prepare a verified Music Video Director production without launching it.',
  useWhen: 'The user asks to prepare a Story music video for later launch.',
  parameters: ['target_story_title', 'song_name', 'cue_title', 'pacing', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'stage_story_music_video' }, pacing: { type: 'string', enum: ['cinematic', 'balanced', 'rhythmic'] }, confirm: { const: true } }, required: ['type', 'confirm'] },
  risk: 'edit', confirmation: 'required', progress: 'Preparando el videoclip de Story en Director…',
  resolve(raw) { const pacing = text(raw.pacing, 20); return raw.confirm === true ? { type: 'stage_story_music_video', targetStoryTitle: text(raw.target_story_title, 300), songName: text(raw.song_name, 300), cueTitle: text(raw.cue_title, 300), pacing: pacing === 'cinematic' || pacing === 'rhythmic' ? pacing : 'balanced', confirm: true } : null },
  validate(action) { return action.confirm === true ? [] : ['confirmation is required'] }, async prepare(action) { return action }, async execute(action, context) { return context.adapters.storyLab.stageMusicVideo(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'director_production', successState: 'prepared' }, summarize(_action, outcome) { return outcome.message }, presentation: { destination: 'director', anchors: ['production', 'music'], replay: 'atomic' },
})

const sceneCapabilityMeta: Record<AgentSceneWorkflowAction['type'], { title: string; description: string; risk: CapabilityRisk }> = {
  create_3d_scene: { title: 'Create a 3D scene', description: 'Create a named blank editable Video3D scene.', risk: 'edit' },
  set_3d_scene_properties: { title: 'Set 3D scene properties', description: 'Set duration, canvas size and frame rate.', risk: 'edit' },
  add_3d_scene_layer: { title: 'Add a 3D scene layer', description: 'Add an exact gallery output or camera as an editable layer.', risk: 'edit' },
  update_3d_scene_layer: { title: 'Update a 3D scene layer', description: 'Change supported layer properties by exact name.', risk: 'edit' },
  remove_3d_scene_layer: { title: 'Remove a 3D scene layer', description: 'Remove an unlocked layer by exact name.', risk: 'edit' },
  attach_3d_scene_audio: { title: 'Attach scene audio', description: 'Attach an exact audio output to the editable scene.', risk: 'edit' },
  analyze_3d_scene_audio: { title: 'Analyze scene audio', description: 'Detect a compact BPM, beats and downbeats grid once.', risk: 'compute' },
  apply_3d_choreography: { title: 'Apply 3D choreography', description: 'Bake an analyzed rhythm grid into ordinary editable keyframes.', risk: 'edit' },
}

function sceneWorkflowAction(type: AgentSceneWorkflowAction['type'], raw: Record<string, unknown>): AgentSceneWorkflowAction | null {
  if (raw.confirm !== true) return null
  const sceneName = text(raw.scene_name, 300)
  if (!sceneName) return null
  if (type === 'create_3d_scene') return { type, sceneName, durationSeconds: boundedNumber(raw.duration_seconds, 1, 300, 5), width: boundedNumber(raw.width, 320, 7680, 1280), height: boundedNumber(raw.height, 240, 4320, 720), fps: raw.fps === 60 ? 60 : 30, confirm: true }
  if (type === 'set_3d_scene_properties') return { type, sceneName, durationSeconds: raw.duration_seconds === undefined ? undefined : boundedNumber(raw.duration_seconds, 1, 300, 5), width: raw.width === undefined ? undefined : boundedNumber(raw.width, 320, 7680, 1280), height: raw.height === undefined ? undefined : boundedNumber(raw.height, 240, 4320, 720), fps: raw.fps === undefined ? undefined : raw.fps === 60 ? 60 : 30, confirm: true }
  const layerName = text(raw.layer_name, 300)
  if (type === 'add_3d_scene_layer') {
    const layerType = text(raw.layer_type, 30) as Extract<AgentSceneWorkflowAction, { type: 'add_3d_scene_layer' }>['layerType']
    if (!layerName || !['model3d', 'image', 'video', 'overlay', 'camera'].includes(layerType)) return null
    return { type, sceneName, layerName, layerType, outputName: text(raw.output_name, 300), confirm: true }
  }
  if (type === 'update_3d_scene_layer') return layerName ? { type, sceneName, layerName, visible: typeof raw.visible === 'boolean' ? raw.visible : undefined, locked: typeof raw.locked === 'boolean' ? raw.locked : undefined, confirm: true } : null
  if (type === 'remove_3d_scene_layer') return layerName ? { type, sceneName, layerName, confirm: true } : null
  const audioOutputName = text(raw.audio_output_name, 300)
  if (type === 'attach_3d_scene_audio' || type === 'analyze_3d_scene_audio') return audioOutputName ? { type, sceneName, audioOutputName, confirm: true } : null
  const cueSource = text(raw.cue_source, 30)
  const profile = text(raw.rhythm_profile, 30)
  return layerName && audioOutputName && rhythmCueSources.has(cueSource) && rhythmProfiles.has(profile)
    ? { type, sceneName, layerName, audioOutputName, cueSource: cueSource as 'beats' | 'downbeats', profile: profile as 'pulse' | 'bounce' | 'peek' | 'camera-punch', intensity: boundedNumber(raw.intensity, 0, 1, .65), confirm: true }
    : null
}

for (const type of Object.keys(sceneCapabilityMeta) as AgentSceneWorkflowAction['type'][]) {
  const meta = sceneCapabilityMeta[type]
  defineCapability<AgentSceneWorkflowAction>({
    name: type, title: meta.title, description: meta.description,
    useWhen: `Use ${type} for one explicit, visible Video3D edit.`,
    parameters: ['scene_name', 'layer_name', 'layer_type', 'output_name', 'audio_output_name', 'duration_seconds', 'width', 'height', 'fps', 'visible', 'locked', 'cue_source', 'rhythm_profile', 'intensity', 'confirm'],
    inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: type }, scene_name: { type: 'string' }, confirm: { const: true } }, required: ['type', 'scene_name', 'confirm'] },
    risk: meta.risk, confirmation: 'required', progress: `${meta.title}…`,
    resolve(raw) { return sceneWorkflowAction(type, raw) },
    validate(action) { return action.type === type && action.confirm === true ? [] : [`${type} is invalid`] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.video3d.run(action) },
    correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_3d_scene', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_3d', anchors: ['scene', 'layers', 'timeline'], replay: 'atomic' },
  })
}

function defineSceneControlCapability<T extends AgentOpen3dSceneAction | AgentSave3dSceneAction | AgentExport3dSceneAction>(
  type: T['type'], title: string, risk: CapabilityRisk,
): void {
  defineCapability<T>({
    name: type, title, description: `${title} through the common Video3D application adapter.`, useWhen: `The user explicitly asks to ${title.toLowerCase()}.`,
    parameters: ['scene_name', 'layer_name', 'confirm'],
    inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: type }, scene_name: { type: 'string' }, layer_name: { type: 'string' }, confirm: { const: true } }, required: ['type', 'scene_name', 'confirm'] },
    risk, confirmation: 'required', progress: `${title}…`,
    resolve(raw) {
      if (raw.confirm !== true || !text(raw.scene_name, 300)) return null
      const base = { type, sceneName: text(raw.scene_name, 300), confirm: true }
      return (type === 'open_3d_scene' ? { ...base, layerName: text(raw.layer_name, 300) } : base) as T
    },
    validate(action) { return action.sceneName && action.confirm === true ? [] : ['scene name and confirmation are required'] },
    async prepare(action) { return action },
    async execute(action, context) {
      const outcome = await context.adapters.video3d.control(action)
      return outcome
    },
    correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_3d_scene', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_3d', anchors: ['scene'], replay: 'atomic' },
  })
}

defineSceneControlCapability<AgentOpen3dSceneAction>('open_3d_scene', 'Open a saved 3D scene', 'read')
defineSceneControlCapability<AgentSave3dSceneAction>('save_3d_scene', 'Save the editable 3D scene', 'edit')
defineSceneControlCapability<AgentExport3dSceneAction>('export_3d_scene', 'Export the 3D scene MP4', 'compute')

export function getCapability(name: string): CapabilityDefinition | undefined {
  return definitions.get(name)
}

export function listCapabilities(): CapabilityDefinition[] {
  return [...definitions.values()]
}

export function parseRegisteredCapability(
  name: string,
  raw: Record<string, unknown>,
): AgentAction | null | undefined {
  const definition = definitions.get(name)
  if (!definition) return undefined
  const action = definition.resolve(raw)
  return action && definition.validate(action).length === 0 ? action : null
}

export async function executeRegisteredCapability(
  action: AgentAction,
  context: CapabilityExecutionContext,
): Promise<CapabilityExecutionOutcome | undefined> {
  const definition = definitions.get(action.type)
  if (!definition) return undefined
  const errors = definition.validate(action)
  if (errors.length) throw new Error(errors.join('; '))
  const prepared = await definition.prepare(action, context)
  const outcome = await definition.execute(prepared, context)
  const tracked = await definition.track(prepared, outcome, context)
  return { ...tracked, message: definition.summarize(prepared, tracked) }
}

export function registeredCapabilitySchemas(): Record<string, unknown>[] {
  return listCapabilities().map(capability => capability.inputSchema)
}

export function registeredCapabilityDocumentationRows(): string[] {
  return listCapabilities().map(capability => (
    `| \`${capability.name}\` | ${capability.risk} | ${capability.confirmation} | ${capability.description} |`
  ))
}
