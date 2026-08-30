import type {
  AgentAction,
  AgentApply3dRhythmAction,
  AgentOpenTabAction,
} from './agentActions'
import type { AgentExecutionReport } from './agentContract'

export const AGENT_TABS = [
  'studio', 'director', 'productions', 'images', 'videos', 'audio', '3d',
  'story_lab', 'series_lab', 'comics', 'video_editor', 'video_3d', 'animate_3d',
  'character_creator', 'character_kit', 'workspaces', 'settings',
] as const

export type AgentTab = typeof AGENT_TABS[number]
export type CapabilityRisk = 'read' | 'edit' | 'compute' | 'external_cost'
export type CapabilityConfirmation = 'none' | 'required'

export interface CapabilityPresentation {
  destination: AgentTab
  anchors: string[]
  replay: 'atomic'
}

export interface CapabilityExecutionOutcome {
  message: string
  report?: AgentExecutionReport
}

export interface CapabilityExecutionContext {
  openTab(tab: AgentTab): string | Promise<string>
  apply3dRhythm(action: AgentApply3dRhythmAction): Promise<string>
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
  execute(action: TAction, context: CapabilityExecutionContext): Promise<CapabilityExecutionOutcome>
  track: {
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
  async execute(action, context) {
    return { message: await context.openTab(action.tab) }
  },
  track: { targetKind: 'application_section', successState: 'completed' },
  summarize(_action, outcome) { return outcome.message },
  presentation: { destination: 'studio', anchors: [], replay: 'atomic' },
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
  async execute(action, context) {
    await context.openTab('video_3d')
    return { message: await context.apply3dRhythm(action) }
  },
  track: { targetKind: 'video_3d_scene', successState: 'prepared' },
  summarize(_action, outcome) { return outcome.message },
  presentation: {
    destination: 'video_3d',
    anchors: ['scene', 'layer', 'audio', 'rhythm-profile', 'intensity'],
    replay: 'atomic',
  },
})

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
  const outcome = await definition.execute(action, context)
  return { ...outcome, message: definition.summarize(action, outcome) }
}

export function registeredCapabilitySchemas(): Record<string, unknown>[] {
  return listCapabilities().map(capability => capability.inputSchema)
}

export function registeredCapabilityDocumentationRows(): string[] {
  return listCapabilities().map(capability => (
    `| \`${capability.name}\` | ${capability.risk} | ${capability.confirmation} | ${capability.description} |`
  ))
}
