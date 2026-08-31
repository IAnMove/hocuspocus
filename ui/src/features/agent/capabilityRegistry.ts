import type {
  AgentAction,
  AgentApply3dRhythmAction,
  AgentApplySeriesPlanAction,
  AgentAssembleSeriesEpisodeAction,
  AgentCommitSeriesCanonAction,
  AgentApplyStoryProposalAction,
  AgentApproveStorySectionAction,
  AgentApproveStoryVisualsAction,
  AgentCreateRhythmic3dVideoAction,
  AgentSceneWorkflowAction,
  AgentOpen3dSceneAction,
  AgentSave3dSceneAction,
  AgentExport3dSceneAction,
  AgentCreateComicAction,
  AgentCreateSeriesEpisodeAction,
  AgentCreateStoryAction,
  AgentGenerateComicAction,
  AgentGenerateSeriesPlanAction,
  AgentGenerateStorySectionAction,
  AgentGenerateStoryVisualsAction,
  AgentRenderSeriesShotsAction,
  AgentReviewSeriesAttemptsAction,
  AgentStageStoryComicAction,
  AgentStartDirectorProductionAction,
  AgentStageStoryVideoAction,
  AgentStageStoryMusicVideoAction,
  AgentUpdateStoryAction,
  AgentUpdateSeriesEpisodeAction,
  AgentOpenTabAction,
} from './agentActions'
import { useStore } from '../../stores/useStore'
import type { AgentExecutionReport } from './agentContract'
import type { AgentExecutionTarget } from './agentContract'
import { executionKey, executionReport } from './agentContract'
import type { WizardApplicationAdapters } from './applicationAdapters'
import type { AgentAttachCharacterKitReferencesAction, AgentBuildCharacterKitAction, AgentCreateCharacterKitAction, AgentOpenCharacterKitAction, AgentOpenCharacterKitRigAction } from './characterKitActions'

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
  assetIds?: string[]
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
const storyProjectTypes = new Set(['full_story', 'music_video', 'trailer', 'quick_video'])
const storyProposalScopes = new Set(['all', 'overview', 'world', 'characters', 'relationships', 'structure'])
const storyApprovalSections = new Set(['overview', 'world', 'characters', 'relationships', 'structure'])
const storyVisualScopes = new Set(['world', 'locations', 'characters', 'all'])
const storyVisualTargetKinds = new Set(['world', 'location', 'character'])
const seriesPlanScopes = new Set(['outline', 'script', 'shots', 'complete'])
const seriesRenderModes = new Set(['selected', 'missing', 'failed', 'all'])
const seriesReviewScopes = new Set(['selected_latest', 'all_latest'])
const seriesReviewDecisions = new Set(['approve', 'reject'])
const seriesCanonDecisions = new Set(['accept_all', 'reject_all', 'accept_selected', 'reject_selected'])

function storyCharacters(value: unknown): AgentCreateStoryAction['characters'] {
  return Array.isArray(value) ? value.slice(0, 16).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const name = text(raw.name, 160)
    return name ? [{
      name, role: text(raw.role, 300), personality: text(raw.personality, 1_000),
      desire: text(raw.desire, 1_000), flaw: text(raw.flaw, 1_000),
      appearance: text(raw.appearance, 1_000), voice: text(raw.voice, 1_000),
    }] : []
  }) : []
}

function storyLocations(value: unknown): AgentCreateStoryAction['locations'] {
  return Array.isArray(value) ? value.slice(0, 16).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const name = text(raw.name, 160)
    return name ? [{ name, purpose: text(raw.purpose, 1_000), description: text(raw.description, 1_500) }] : []
  }) : []
}

function storyOutlineBeats(value: unknown): string[] {
  return Array.isArray(value) ? value.slice(0, 24).flatMap(item => {
    const beat = text(item, 1_500)
    return beat ? [beat] : []
  }) : []
}

function optionalStoryDuration(value: unknown): number | undefined {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return undefined
  return Math.round(Math.min(3_600, Math.max(15, value)))
}

function storyVisualSelections(value: unknown): AgentApproveStoryVisualsAction['selections'] {
  return Array.isArray(value) ? value.slice(0, 40).flatMap(item => {
    if (!item || typeof item !== 'object' || Array.isArray(item)) return []
    const raw = item as Record<string, unknown>
    const targetKind = text(raw.target_kind, 30)
    const assetName = text(raw.asset_name, 300)
    const targetName = text(raw.target_name, 300)
    if (!storyVisualTargetKinds.has(targetKind) || !assetName || (targetKind !== 'world' && !targetName)) return []
    return [{ targetKind: targetKind as AgentApproveStoryVisualsAction['selections'][number]['targetKind'], targetName, assetName, primary: raw.primary === true }]
  }) : []
}

function storyFields(raw: Record<string, unknown>) {
  return {
    title: text(raw.title, 300),
    creativeBrief: text(raw.creative_brief, 4_000),
    premise: text(raw.premise, 2_000),
    logline: text(raw.logline, 2_000),
    synopsis: text(raw.synopsis, 6_000),
    theme: text(raw.theme, 1_000),
    ending: text(raw.ending, 2_000),
    genre: text(raw.genre, 300),
    tone: text(raw.tone, 500),
    visualStyle: text(raw.visual_style, 2_000),
    worldSummary: text(raw.world_summary, 3_000),
    language: text(raw.language, 120),
    characters: storyCharacters(raw.characters),
    locations: storyLocations(raw.locations),
    outlineBeats: storyOutlineBeats(raw.outline_beats),
    durationSeconds: optionalStoryDuration(raw.target_duration_seconds),
  }
}

function seriesEpisodeFields(raw: Record<string, unknown>) {
  return {
    seriesTitle: text(raw.series_title, 300), seriesPremise: text(raw.series_premise, 3_000), seriesLogline: text(raw.series_logline, 2_000),
    episodeTitle: text(raw.episode_title, 300), episodePremise: text(raw.episode_premise, 3_000), episodeLogline: text(raw.episode_logline, 2_000),
    genre: text(raw.genre, 300), tone: text(raw.tone, 500), visualStyle: text(raw.visual_style, 2_000), worldSummary: text(raw.world_summary, 3_000), theme: text(raw.theme, 1_000), ending: text(raw.ending, 2_000), language: text(raw.language, 120),
    characters: storyCharacters(raw.characters), locations: storyLocations(raw.locations), outlineBeats: storyOutlineBeats(raw.outline_beats), targetDurationSeconds: optionalStoryDuration(raw.target_duration_seconds),
  }
}

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

defineCapability<AgentCreateCharacterKitAction>({
  name: 'create_character_kit', title: 'Create a Character Kit', description: 'Create or reopen one canonical Character Kit and return its real ID.', useWhen: 'The user asks to create a named Character Kit.', parameters: ['kit_name', 'style'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'create_character_kit' }, kit_name: { type: 'string', maxLength: 160 }, style: { type: 'string', enum: ['cutout', 'children-illustration', 'anime-2d'] } }, required: ['type', 'kit_name'] }, risk: 'edit', confirmation: 'none', progress: 'Creando el Character Kit…',
  resolve(raw) { const name = text(raw.kit_name, 160); const style = text(raw.style, 40); return name && (style === 'cutout' || style === 'children-illustration' || style === 'anime-2d') ? { type: 'create_character_kit', name, style } : null },
  validate(action) { return action.name ? [] : ['kit name is required'] }, async prepare(action) { return action }, async execute(action, context) { return context.adapters.characterKit.create(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome }, report: { targetKind: 'character_kit', successState: 'completed' }, summarize(_action, outcome) { return outcome.message }, presentation: { destination: 'character_kit', anchors: ['kit'], replay: 'atomic' },
})

defineCapability<AgentOpenCharacterKitAction>({
  name: 'open_character_kit', title: 'Open a Character Kit', description: 'Open one exact canonical Character Kit.', useWhen: 'The user asks to open a Character Kit.', parameters: ['kit_name'], inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'open_character_kit' }, kit_name: { type: 'string', maxLength: 160 } }, required: ['type'] }, risk: 'read', confirmation: 'none', progress: 'Abriendo Character Kit…',
  resolve(raw) { return { type: 'open_character_kit', kitName: text(raw.kit_name, 160) } }, validate() { return [] }, async prepare(action) { return action }, async execute(action, context) { return context.adapters.characterKit.openKit(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome }, report: { targetKind: 'character_kit', successState: 'completed' }, summarize(_action, outcome) { return outcome.message }, presentation: { destination: 'character_kit', anchors: ['kit'] },
})

defineCapability<AgentAttachCharacterKitReferencesAction>({
  name: 'attach_character_kit_references', title: 'Attach a Character Kit identity reference', description: 'Attach one exact existing image output as the kit identity reference.', useWhen: 'The user explicitly asks to use an image as a Character Kit identity.', parameters: ['kit_name', 'reference_output_names'], inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'attach_character_kit_references' }, kit_name: { type: 'string' }, reference_output_names: { type: 'array', minItems: 1, maxItems: 1, items: { type: 'string' } } }, required: ['type', 'reference_output_names'] }, risk: 'edit', confirmation: 'none', progress: 'Vinculando la identidad del Character Kit…',
  resolve(raw) { const names = Array.isArray(raw.reference_output_names) ? raw.reference_output_names.flatMap(value => { const name = text(value, 300); return name ? [name] : [] }).slice(0, 2) : []; return names.length === 1 ? { type: 'attach_character_kit_references', kitName: text(raw.kit_name, 160), outputNames: names } : null }, validate(action) { return action.outputNames.length === 1 ? [] : ['one exact identity reference is required'] }, async prepare(action) { return action }, async execute(action, context) { return context.adapters.characterKit.attachReference(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome }, report: { targetKind: 'character_kit', successState: 'completed' }, summarize(_action, outcome) { return outcome.message }, presentation: { destination: 'character_kit', anchors: ['identity-reference'], replay: 'atomic' },
})

function characterKitNamedAction<T extends AgentBuildCharacterKitAction | AgentOpenCharacterKitRigAction>(type: T['type'], title: string, execute: (action: T, context: CapabilityExecutionContext) => Promise<CapabilityExecutionOutcome>) { defineCapability<T>({ name: type, title, description: `${title} for one canonical Character Kit.`, useWhen: `The user explicitly asks to ${title.toLowerCase()}.`, parameters: ['kit_name'], inputSchema: { type: 'object', properties: { type: { const: type }, kit_name: { type: 'string' } }, required: ['type'] }, risk: 'edit', confirmation: 'none', progress: `${title}…`, resolve(raw) { return { type, kitName: text(raw.kit_name, 160) } as T }, validate() { return [] }, async prepare(action) { return action }, execute, correlate(_a, o) { return o.target }, async track(_a, o) { return o }, report: { targetKind: 'character_kit', successState: 'completed' }, summarize(_a, o) { return o.message }, presentation: { destination: 'character_kit', anchors: ['kit'], replay: 'atomic' } }) }
characterKitNamedAction<AgentBuildCharacterKitAction>('build_character_kit', 'Build Character Kit', (action, context) => context.adapters.characterKit.build(action))
characterKitNamedAction<AgentOpenCharacterKitRigAction>('open_character_kit_rig', 'Open Character Kit Face Rig', (action, context) => context.adapters.characterKit.openRig(action))

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

defineCapability<AgentCreateStoryAction>({
  name: 'create_story', title: 'Create a filled Story Lab project',
  description: 'Create a new editable Story Lab project with its canon, characters, locations and outline, then return its canonical project ID.',
  useWhen: 'The user asks for a new story, episode, trailer, music video or a filled example in Story Lab.',
  parameters: ['title', 'project_type', 'premise', 'creative_brief', 'characters', 'locations', 'outline_beats', 'target_duration_seconds'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'create_story' }, title: { type: 'string', maxLength: 300 }, premise: { type: 'string', maxLength: 2_000 }, project_type: { type: 'string', enum: ['full_story', 'music_video', 'trailer', 'quick_video'] } }, required: ['type', 'title', 'premise'] },
  risk: 'edit', confirmation: 'none', progress: 'Escribiendo y guardando la nueva historia…',
  resolve(raw) {
    const fields = storyFields(raw)
    if (!fields.title || !fields.premise) return null
    const projectType = text(raw.project_type, 30)
    return { type: 'create_story', ...fields, projectType: storyProjectTypes.has(projectType) ? projectType as AgentCreateStoryAction['projectType'] : 'full_story' }
  },
  validate(action) { return action.title && action.premise ? [] : ['title and premise are required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.storyLab.create(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'story', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'story_lab', anchors: ['overview', 'characters', 'world', 'structure'], replay: 'atomic' },
})

defineCapability<AgentUpdateStoryAction>({
  name: 'update_story', title: 'Update a filled Story Lab project',
  description: 'Apply an explicit patch to one canonical Story Lab project and return that project’s real ID.',
  useWhen: 'The user asks to change an existing Story Lab story, its canon, characters, locations or outline.',
  parameters: ['target_story_title', 'title', 'premise', 'creative_brief', 'characters', 'locations', 'outline_beats', 'target_duration_seconds'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'update_story' }, target_story_title: { type: 'string', maxLength: 300 } }, required: ['type'] },
  risk: 'edit', confirmation: 'none', progress: 'Actualizando el canon de la historia…',
  resolve(raw) {
    const fields = storyFields(raw)
    const action: AgentUpdateStoryAction = { type: 'update_story', targetStoryTitle: text(raw.target_story_title, 300), ...fields }
    const hasPatch = action.title || action.creativeBrief || action.premise || action.logline || action.synopsis || action.theme || action.ending || action.genre || action.tone || action.visualStyle || action.worldSummary || action.language || action.characters.length || action.locations.length || action.outlineBeats.length || action.durationSeconds !== undefined
    return hasPatch ? action : null
  },
  validate(action) { return action.targetStoryTitle || action.title || action.premise ? [] : ['a target story or a patch is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.storyLab.update(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'story', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'story_lab', anchors: ['overview', 'characters', 'world', 'structure'], replay: 'atomic' },
})

defineCapability<AgentGenerateStorySectionAction>({
  name: 'generate_story_section', title: 'Generate a reviewable Story Lab proposal',
  description: 'Generate a proposal for an exact Story Lab section without modifying or approving the project canon.',
  useWhen: 'The user explicitly asks to generate a Story Lab proposal for review.',
  parameters: ['target_story_title', 'story_generation_scope', 'instruction', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'generate_story_section' }, story_generation_scope: { type: 'string', enum: ['all', 'overview', 'world', 'characters', 'relationships', 'structure'] }, confirm: { const: true } }, required: ['type', 'story_generation_scope', 'confirm'] },
  risk: 'compute', confirmation: 'required', progress: 'Invocando una propuesta revisable de Story Lab…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const scope = text(raw.story_generation_scope, 40)
    return storyProposalScopes.has(scope) ? { type: 'generate_story_section', targetStoryTitle: text(raw.target_story_title, 300), scope: scope as AgentGenerateStorySectionAction['scope'], instruction: text(raw.instruction, 4_000), confirm: true } : null
  },
  validate(action) { return action.confirm === true && storyProposalScopes.has(action.scope) ? [] : ['a confirmed valid proposal scope is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.storyLab.generateProposal(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'story', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'story_lab', anchors: ['proposal', 'review'], replay: 'atomic' },
})

defineCapability<AgentApplyStoryProposalAction>({
  name: 'apply_story_proposal', title: 'Apply a reviewed Story Lab proposal',
  description: 'Apply the previously generated proposal for one exact Story Lab project and invalidate only the approvals it changes.',
  useWhen: 'The user explicitly confirms that the saved Story Lab proposal should become canon.',
  parameters: ['target_story_title', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'apply_story_proposal' }, target_story_title: { type: 'string', maxLength: 300 }, confirm: { const: true } }, required: ['type', 'confirm'] },
  risk: 'edit', confirmation: 'required', progress: 'Aplicando la propuesta revisada al canon…',
  resolve(raw) { return raw.confirm === true ? { type: 'apply_story_proposal', targetStoryTitle: text(raw.target_story_title, 300), confirm: true } : null },
  validate(action) { return action.confirm === true ? [] : ['confirmation is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.storyLab.applyProposal(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'story', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'story_lab', anchors: ['proposal', 'review'], replay: 'atomic' },
})

defineCapability<AgentApproveStorySectionAction>({
  name: 'approve_story_section', title: 'Approve a Story Lab canon section',
  description: 'Validate and approve one exact current-version Story Lab section.',
  useWhen: 'The user explicitly asks to approve a reviewed Story Lab canon section.',
  parameters: ['target_story_title', 'story_section', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'approve_story_section' }, story_section: { type: 'string', enum: ['overview', 'world', 'characters', 'relationships', 'structure'] }, confirm: { const: true } }, required: ['type', 'story_section', 'confirm'] },
  risk: 'edit', confirmation: 'required', progress: 'Validando y aprobando el canon…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const section = text(raw.story_section, 40)
    return storyApprovalSections.has(section) ? { type: 'approve_story_section', targetStoryTitle: text(raw.target_story_title, 300), section: section as AgentApproveStorySectionAction['section'], confirm: true } : null
  },
  validate(action) { return action.confirm === true && storyApprovalSections.has(action.section) ? [] : ['a confirmed valid Story section is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.storyLab.approveSection(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'story', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'story_lab', anchors: ['review', 'approval'], replay: 'atomic' },
})

defineCapability<AgentGenerateStoryVisualsAction>({
  name: 'generate_story_visuals', title: 'Generate exact Story Lab visual references',
  description: 'Render the requested Story Lab visual references, attach them to the canonical project and return every new asset ID.',
  useWhen: 'The user explicitly asks to generate the visual references for a Story Lab project.',
  parameters: ['target_story_title', 'story_visual_scope', 'target_names', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'generate_story_visuals' }, story_visual_scope: { type: 'string', enum: ['world', 'locations', 'characters', 'all'] }, target_names: { type: 'array', items: { type: 'string' } }, confirm: { const: true } }, required: ['type', 'story_visual_scope', 'confirm'] },
  risk: 'compute', confirmation: 'required', progress: 'Generando y correlacionando referencias visuales…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const scope = text(raw.story_visual_scope, 30)
    if (!storyVisualScopes.has(scope)) return null
    const targetNames = Array.isArray(raw.target_names) ? raw.target_names.slice(0, 40).flatMap(value => {
      const name = text(value, 300)
      return name ? [name] : []
    }) : []
    return { type: 'generate_story_visuals', targetStoryTitle: text(raw.target_story_title, 300), scope: scope as AgentGenerateStoryVisualsAction['scope'], targetNames, confirm: true }
  },
  validate(action) { return action.confirm === true && storyVisualScopes.has(action.scope) ? [] : ['a confirmed valid visual scope is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.storyLab.generateVisuals(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'story', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'story_lab', anchors: ['assets', 'references'], replay: 'atomic' },
})

defineCapability<AgentApproveStoryVisualsAction>({
  name: 'approve_story_visuals', title: 'Approve exact Story Lab visual references',
  description: 'Resolve named visual assets unambiguously, attach them to their Story Lab targets and approve them.',
  useWhen: 'The user explicitly asks to approve named Story Lab visual references.',
  parameters: ['target_story_title', 'story_visual_selections', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'approve_story_visuals' }, story_visual_selections: { type: 'array' }, confirm: { const: true } }, required: ['type', 'story_visual_selections', 'confirm'] },
  risk: 'edit', confirmation: 'required', progress: 'Vinculando y aprobando referencias visuales…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const selections = storyVisualSelections(raw.story_visual_selections)
    return selections.length ? { type: 'approve_story_visuals', targetStoryTitle: text(raw.target_story_title, 300), selections, confirm: true } : null
  },
  validate(action) { return action.confirm === true && action.selections.length ? [] : ['confirmed visual selections are required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.storyLab.approveVisuals(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'story', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'story_lab', anchors: ['assets', 'references', 'approval'], replay: 'atomic' },
})

defineCapability<AgentStageStoryComicAction>({
  name: 'stage_story_comic', title: 'Stage a Story Lab comic in Comic Director',
  description: 'Create a new editable Comic Director project from an exact Story Lab project, then verify its linked Story production and comic ID.',
  useWhen: 'The user explicitly asks to turn a Story Lab project into a filled comic without rendering its artwork yet.',
  parameters: ['target_story_title', 'direction', 'page_count', 'panels_per_page', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'stage_story_comic' }, target_story_title: { type: 'string', maxLength: 300 }, page_count: { type: 'integer', minimum: 1, maximum: 100 }, panels_per_page: { type: 'integer', minimum: 1, maximum: 12 }, confirm: { const: true } }, required: ['type', 'confirm'] },
  risk: 'edit', confirmation: 'required', progress: 'Convirtiendo la historia en un cómic editable…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    return { type: 'stage_story_comic', targetStoryTitle: text(raw.target_story_title, 300), direction: text(raw.direction, 4_000), pageCount: Math.round(boundedNumber(raw.page_count, 1, 100, 4)), panelsPerPage: Math.round(boundedNumber(raw.panels_per_page, 1, 12, 4)), confirm: true }
  },
  validate(action) { return action.confirm === true && action.pageCount >= 1 && action.panelsPerPage >= 1 ? [] : ['confirmed page and panel counts are required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.storyLab.stageComic(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'comic', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'comics', anchors: ['project', 'pages', 'panels'], replay: 'atomic' },
})

defineCapability<AgentCreateSeriesEpisodeAction>({
  name: 'create_series_episode', title: 'Create a filled Series Lab episode',
  description: 'Create or resolve a series, save its editable canon and create one exact episode with its canonical episode ID.',
  useWhen: 'The user asks for a new, filled episode in Series Lab.',
  parameters: ['series_title', 'episode_title', 'episode_premise', 'create_if_missing', 'characters', 'locations', 'outline_beats'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'create_series_episode' }, series_title: { type: 'string', maxLength: 300 }, episode_premise: { type: 'string', maxLength: 3_000 }, create_if_missing: { type: 'boolean' } }, required: ['type', 'series_title', 'episode_premise'] },
  risk: 'edit', confirmation: 'none', progress: 'Creando el episodio editable de Series Lab…',
  resolve(raw) {
    const fields = seriesEpisodeFields(raw)
    if (!fields.seriesTitle || !fields.episodePremise) return null
    return { type: 'create_series_episode', ...fields, createIfMissing: raw.create_if_missing === true, knownUniverse: raw.known_universe === true }
  },
  validate(action) { return action.seriesTitle && action.episodePremise ? [] : ['series title and episode premise are required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.seriesLab.createEpisode(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'series_episode', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'series_lab', anchors: ['setup', 'canon', 'episode'], replay: 'atomic' },
})

defineCapability<AgentUpdateSeriesEpisodeAction>({
  name: 'update_series_episode', title: 'Update a Series Lab episode',
  description: 'Apply an explicit non-destructive episode patch and return the canonical episode ID.',
  useWhen: 'The user asks to modify one existing Series Lab episode.',
  parameters: ['series_title', 'target_episode_title', 'episode_title', 'episode_premise', 'episode_logline', 'outline_beats', 'target_duration_seconds'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'update_series_episode' }, series_title: { type: 'string', maxLength: 300 }, target_episode_title: { type: 'string', maxLength: 300 } }, required: ['type'] },
  risk: 'edit', confirmation: 'none', progress: 'Actualizando el episodio de Series Lab…',
  resolve(raw) {
    const fields = seriesEpisodeFields(raw)
    const action: AgentUpdateSeriesEpisodeAction = { type: 'update_series_episode', seriesTitle: fields.seriesTitle, targetEpisodeTitle: text(raw.target_episode_title, 300), episodeTitle: fields.episodeTitle, episodePremise: fields.episodePremise, episodeLogline: fields.episodeLogline, outlineBeats: fields.outlineBeats, targetDurationSeconds: fields.targetDurationSeconds }
    return action.episodeTitle || action.episodePremise || action.episodeLogline || action.outlineBeats.length || action.targetDurationSeconds !== undefined ? action : null
  },
  validate(action) { return action.episodeTitle || action.episodePremise || action.episodeLogline || action.outlineBeats.length || action.targetDurationSeconds !== undefined ? [] : ['an episode patch is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.seriesLab.updateEpisode(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'series_episode', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'series_lab', anchors: ['episode'], replay: 'atomic' },
})

defineCapability<AgentGenerateSeriesPlanAction>({
  name: 'generate_series_plan', title: 'Generate a recoverable Series Lab plan',
  description: 'Start planning for one exact episode and return its real recoverable planning job ID without applying it.',
  useWhen: 'The user explicitly asks to generate an episode outline, script, shots or complete plan.',
  parameters: ['series_title', 'target_episode_title', 'series_plan_scope', 'instruction', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'generate_series_plan' }, series_plan_scope: { type: 'string', enum: ['outline', 'script', 'shots', 'complete'] }, confirm: { const: true } }, required: ['type', 'series_plan_scope', 'confirm'] },
  risk: 'compute', confirmation: 'required', progress: 'Generando un plan recuperable de Series Lab…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const scope = text(raw.series_plan_scope, 40)
    return seriesPlanScopes.has(scope) ? { type: 'generate_series_plan', seriesTitle: text(raw.series_title, 300), targetEpisodeTitle: text(raw.target_episode_title, 300), scope: scope as AgentGenerateSeriesPlanAction['scope'], instruction: text(raw.instruction, 4_000), confirm: true } : null
  },
  validate(action) { return action.confirm === true && seriesPlanScopes.has(action.scope) ? [] : ['a confirmed planning scope is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.seriesLab.generatePlan(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'series_episode', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'series_lab', anchors: ['episode', 'plan'], replay: 'atomic' },
})

defineCapability<AgentApplySeriesPlanAction>({
  name: 'apply_series_plan', title: 'Apply a completed Series Lab plan',
  description: 'Apply only a completed planning job belonging to the exact episode, without rendering or committing canon.',
  useWhen: 'The user explicitly asks to apply a completed Series Lab proposal.',
  parameters: ['series_title', 'target_episode_title', 'job_id', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'apply_series_plan' }, job_id: { type: 'string', maxLength: 160 }, confirm: { const: true } }, required: ['type', 'confirm'] },
  risk: 'edit', confirmation: 'required', progress: 'Aplicando el plan al episodio exacto…',
  resolve(raw) { return raw.confirm === true ? { type: 'apply_series_plan', seriesTitle: text(raw.series_title, 300), targetEpisodeTitle: text(raw.target_episode_title, 300), jobId: text(raw.job_id, 160), confirm: true } : null },
  validate(action) { return action.confirm === true ? [] : ['confirmation is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.seriesLab.applyPlan(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'series_episode', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'series_lab', anchors: ['episode', 'plan'], replay: 'atomic' },
})

defineCapability<AgentRenderSeriesShotsAction>({
  name: 'render_series_shots', title: 'Render eligible Series Lab shots',
  description: 'Queue only eligible shots for the exact episode and return the real recoverable render job ID.',
  useWhen: 'The user explicitly asks to render a Series Lab episode’s shots.',
  parameters: ['series_title', 'target_episode_title', 'render_mode', 'shot_ids', 'seed', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'render_series_shots' }, render_mode: { type: 'string', enum: ['selected', 'missing', 'failed', 'all'] }, shot_ids: { type: 'array', items: { type: 'string' } }, confirm: { const: true } }, required: ['type', 'render_mode', 'confirm'] },
  risk: 'compute', confirmation: 'required', progress: 'Encolando las tomas elegibles de Series Lab…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const mode = text(raw.render_mode, 30)
    const shotIds = Array.isArray(raw.shot_ids) ? raw.shot_ids.slice(0, 200).flatMap(value => { const id = text(value, 160); return id ? [id] : [] }) : []
    if (!seriesRenderModes.has(mode) || (mode === 'selected' && !shotIds.length)) return null
    const seedValue = typeof raw.seed === 'number' && Number.isFinite(raw.seed) ? Math.round(Math.max(-1, Math.min(2_147_483_647, raw.seed))) : undefined
    return { type: 'render_series_shots', seriesTitle: text(raw.series_title, 300), targetEpisodeTitle: text(raw.target_episode_title, 300), mode: mode as AgentRenderSeriesShotsAction['mode'], shotIds, seed: seedValue, confirm: true }
  },
  validate(action) { return action.confirm === true && seriesRenderModes.has(action.mode) && (action.mode !== 'selected' || action.shotIds.length) ? [] : ['a confirmed valid render request is required'] }, async prepare(action) { return action },
  async execute(action, context) { return context.adapters.seriesLab.renderShots(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome },
  report: { targetKind: 'series_episode', successState: 'completed' }, summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'series_lab', anchors: ['review', 'render'], replay: 'atomic' },
})

defineCapability<AgentReviewSeriesAttemptsAction>({
  name: 'review_series_attempts', title: 'Review exact Series Lab attempts', description: 'Approve or reject only reproducible attempts belonging to the exact canonical episode.',
  useWhen: 'The user explicitly asks to approve or reject rendered Series Lab shots.', parameters: ['series_title', 'target_episode_title', 'review_decision', 'review_scope', 'shot_numbers', 'attempt_id', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'review_series_attempts' }, review_decision: { type: 'string', enum: ['approve', 'reject'] }, review_scope: { type: 'string', enum: ['selected_latest', 'all_latest'] }, confirm: { const: true } }, required: ['type', 'review_decision', 'review_scope', 'confirm'] }, risk: 'edit', confirmation: 'required', progress: 'Revisando intentos reproducibles de Series Lab…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const decision = text(raw.review_decision, 30); const scope = text(raw.review_scope, 30)
    const shotNumbers = Array.isArray(raw.shot_numbers) ? raw.shot_numbers.slice(0, 200).flatMap(value => typeof value === 'number' && Number.isInteger(value) && value > 0 ? [value] : []) : []
    if (!seriesReviewDecisions.has(decision) || !seriesReviewScopes.has(scope) || (scope === 'selected_latest' && !shotNumbers.length)) return null
    return { type: 'review_series_attempts', seriesTitle: text(raw.series_title, 300), targetEpisodeTitle: text(raw.target_episode_title, 300), decision: decision as AgentReviewSeriesAttemptsAction['decision'], scope: scope as AgentReviewSeriesAttemptsAction['scope'], shotNumbers, attemptId: text(raw.attempt_id, 160), confirm: true }
  },
  validate(action) { return action.confirm === true ? [] : ['confirmation is required'] }, async prepare(action) { return action }, async execute(action, context) { return context.adapters.seriesLab.reviewAttempts(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome }, report: { targetKind: 'series_episode', successState: 'completed' }, summarize(_action, outcome) { return outcome.message }, presentation: { destination: 'series_lab', anchors: ['review'], replay: 'atomic' },
})

defineCapability<AgentCommitSeriesCanonAction>({
  name: 'commit_series_canon', title: 'Commit reviewed Series canon decisions', description: 'Commit only explicit accepted or rejected canon delta items for the exact episode.',
  useWhen: 'The user explicitly asks to accept or reject proposed Series canon changes.', parameters: ['series_title', 'target_episode_title', 'canon_decision', 'canon_item_ids', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'commit_series_canon' }, canon_decision: { type: 'string', enum: ['accept_all', 'reject_all', 'accept_selected', 'reject_selected'] }, canon_item_ids: { type: 'array', items: { type: 'string' } }, confirm: { const: true } }, required: ['type', 'canon_decision', 'confirm'] }, risk: 'edit', confirmation: 'required', progress: 'Comprometiendo decisiones explícitas de canon…',
  resolve(raw) {
    if (raw.confirm !== true) return null
    const decision = text(raw.canon_decision, 30)
    const itemIds = Array.isArray(raw.canon_item_ids) ? raw.canon_item_ids.slice(0, 200).flatMap(value => { const id = text(value, 160); return id ? [id] : [] }) : []
    if (!seriesCanonDecisions.has(decision) || (decision.endsWith('_selected') && !itemIds.length)) return null
    return { type: 'commit_series_canon', seriesTitle: text(raw.series_title, 300), targetEpisodeTitle: text(raw.target_episode_title, 300), decision: decision as AgentCommitSeriesCanonAction['decision'], itemIds, confirm: true }
  },
  validate(action) { return action.confirm === true ? [] : ['confirmation is required'] }, async prepare(action) { return action }, async execute(action, context) { return context.adapters.seriesLab.commitCanon(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome }, report: { targetKind: 'series_episode', successState: 'completed' }, summarize(_action, outcome) { return outcome.message }, presentation: { destination: 'series_lab', anchors: ['review', 'canon'], replay: 'atomic' },
})

defineCapability<AgentAssembleSeriesEpisodeAction>({
  name: 'assemble_series_episode', title: 'Assemble approved Series Lab shots', description: 'Start a recoverable assembly only when every canonical episode shot has an approved reproducible asset.',
  useWhen: 'The user explicitly asks to assemble the finished Series Lab episode.', parameters: ['series_title', 'target_episode_title', 'confirm'],
  inputSchema: { type: 'object', additionalProperties: false, properties: { type: { const: 'assemble_series_episode' }, confirm: { const: true } }, required: ['type', 'confirm'] }, risk: 'compute', confirmation: 'required', progress: 'Ensamblando el episodio de Series Lab…',
  resolve(raw) { return raw.confirm === true ? { type: 'assemble_series_episode', seriesTitle: text(raw.series_title, 300), targetEpisodeTitle: text(raw.target_episode_title, 300), confirm: true } : null },
  validate(action) { return action.confirm === true ? [] : ['confirmation is required'] }, async prepare(action) { return action }, async execute(action, context) { return context.adapters.seriesLab.assembleEpisode(action) }, correlate(_action, outcome) { return outcome.target }, async track(_action, outcome) { return outcome }, report: { targetKind: 'series_episode', successState: 'completed' }, summarize(_action, outcome) { return outcome.message }, presentation: { destination: 'series_lab', anchors: ['review', 'assembly'], replay: 'atomic' },
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
