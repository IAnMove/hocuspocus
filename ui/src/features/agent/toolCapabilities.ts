/** Capabilities for standalone post-processing tools. */
import type { CapabilityDefinition, defineCapability } from './capabilityRegistry'
import { TOOLS_UPSCALE_METHODS } from '../studio/toolsGenerationSpec'
import toolsCommandCatalog from '../../api/toolsCommandCatalog.json'

const TOOLS_PROCESSOR_SETTINGS_SCHEMA = (
  (toolsCommandCatalog.studio.input as { $defs?: Record<string, unknown> }).$defs?.WangpProcessorSettings
  || { type: 'object', additionalProperties: false, properties: {} }
) as Record<string, unknown>
const TOOLS_PARAMS_SCHEMA = (
  (toolsCommandCatalog.studio.input as { $defs?: Record<string, unknown> }).$defs?.ToolsUpscaleParams
  || {}
) as { properties?: Record<string, unknown> }
const TOOLS_SOURCE_WORKSPACE_SCHEMA = (
  TOOLS_PARAMS_SCHEMA.properties?.source_workspace
  || { type: 'string', minLength: 1, maxLength: 160 }
) as Record<string, unknown>
const TOOLS_SOURCE_WORKSPACE_PATTERN = /^(?:__uploads__|default|[A-Za-z0-9][A-Za-z0-9_-]*)$/

export interface AgentUpscaleAction {
  type: 'upscale'
  /** Exact asset identity when the source is selected from the library. */
  assetId?: string
  /** Canonical local source URL or exact asset ID when supplied directly. */
  source?: string
  sourceWorkspace?: string
  sourceKind: 'image' | 'video'
  method: string
  seed?: number
  wangpProcessorSettings?: Record<string, unknown> | null
  confirm: true
}

export interface AgentRemoveBackgroundAction {
  type: 'remove_background'
  /** Canonical asset identity when the source comes from the library. */
  assetId?: string
  /** Exact canonical filename or API/absolute path resolved by the server. */
  source: string
  sourceWorkspace?: string
  instruction?: string
  confirm: true
}

const registeredRegistrars = new WeakSet<object>()

function text(value: unknown, maxLength: number): string {
  return typeof value === 'string' ? value.trim().slice(0, maxLength) : ''
}

function exactSourceWorkspace(value: unknown): string | null {
  if (typeof value !== 'string' || !value || value.trim() !== value || value.length > 160) return null
  return TOOLS_SOURCE_WORKSPACE_PATTERN.test(value) ? value : null
}
export function registerToolCapabilities(register: typeof defineCapability): void {
  const registrar = register as unknown as object
  if (registeredRegistrars.has(registrar)) return
  registeredRegistrars.add(registrar)

  const definition: CapabilityDefinition<AgentRemoveBackgroundAction> = {
    name: 'remove_background',
    title: 'Remove image or video background',
    description: 'Open Tools and create a transparent PNG or WebM from an exact existing image or video asset.',
    useWhen: 'The user explicitly asks to remove, erase or make an image or video background transparent.',
    parameters: ['asset_id', 'source', 'source_workspace', 'instruction', 'confirm'],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'remove_background' },
        asset_id: { type: 'string', minLength: 1, maxLength: 180 },
        source: { type: 'string', minLength: 1, maxLength: 1_200 },
        source_workspace: { type: 'string', maxLength: 160 },
        instruction: { type: 'string', maxLength: 2_000 },
        confirm: { const: true },
      },
      anyOf: [{ required: ['asset_id'] }, { required: ['source'] }],
      required: ['type', 'confirm'],
    },
    risk: 'compute',
    confirmation: 'required',
    progress: 'Removing the background…',
    resolve(raw) {
      if (raw.confirm !== true) return null
      const assetId = text(raw.asset_id, 180) || undefined
      const source = text(raw.source, 1_200) || undefined
      if (!assetId && !source) return null
      return {
        type: 'remove_background',
        assetId,
        source: source || '',
        sourceWorkspace: text(raw.source_workspace, 160) || undefined,
        instruction: text(raw.instruction, 2_000) || undefined,
        confirm: true,
      }
    },
    validate(action) {
      return action.confirm === true && (Boolean(action.assetId) || Boolean(action.source))
        ? []
        : ['an exact image/video asset_id or source plus confirmation is required']
    },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.tools.removeBackground(action, context.generationContext)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'tool_job', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'studio', anchors: ['tools', 'remove-background'], replay: 'atomic' },
  }
  register(definition)

  const upscaleDefinition: CapabilityDefinition<AgentUpscaleAction> = {
    name: 'upscale',
    title: 'Upscale an image or video',
    description: 'Open Tools and enqueue one exact image or video source through the durable upscale command.',
    useWhen: 'The user explicitly asks to upscale, enlarge or improve the resolution of an existing image or video asset.',
    parameters: [
      'asset_id', 'source', 'source_workspace', 'source_kind', 'method', 'seed',
      'wangp_processor_settings', 'confirm',
    ],
    inputSchema: {
      type: 'object',
      additionalProperties: false,
      properties: {
        type: { const: 'upscale' },
        asset_id: { type: 'string', minLength: 1, maxLength: 240 },
        source: { type: 'string', minLength: 1, maxLength: 8192 },
        source_workspace: TOOLS_SOURCE_WORKSPACE_SCHEMA,
        source_kind: { type: 'string', enum: ['image', 'video'] },
        method: { type: 'string', enum: [...TOOLS_UPSCALE_METHODS] },
        seed: { type: 'integer' },
        wangp_processor_settings: {
          anyOf: [TOOLS_PROCESSOR_SETTINGS_SCHEMA, { type: 'null' }],
        },
        confirm: { const: true },
      },
      anyOf: [{ required: ['asset_id'] }, { required: ['source'] }],
      required: ['type', 'source_kind', 'method', 'confirm'],
    },
    risk: 'compute',
    confirmation: 'required',
    progress: 'Upscaling the selected media…',
    resolve(raw) {
      if (raw.confirm !== true) return null
      const sourceKind = raw.source_kind === 'image' || raw.source_kind === 'video'
        ? raw.source_kind : null
      const method = text(raw.method, 80)
      if (!sourceKind || !TOOLS_UPSCALE_METHODS.includes(method)) return null
      const assetId = text(raw.asset_id, 240) || undefined
      const source = text(raw.source, 8192) || undefined
      if (!assetId && !source) return null
      const sourceWorkspace = raw.source_workspace === undefined || raw.source_workspace === null
        ? undefined
        : exactSourceWorkspace(raw.source_workspace)
      if (raw.source_workspace !== undefined && raw.source_workspace !== null && !sourceWorkspace) return null
      if (raw.seed !== undefined && (typeof raw.seed !== 'number' || !Number.isSafeInteger(raw.seed))) return null
      const settings = raw.wangp_processor_settings
      if (settings !== undefined && settings !== null
          && (typeof settings !== 'object' || Array.isArray(settings))) return null
      return {
        type: 'upscale', sourceKind, method, confirm: true,
        assetId, source,
        sourceWorkspace: sourceWorkspace || undefined,
        ...(raw.seed !== undefined ? { seed: raw.seed as number } : {}),
        ...(settings !== undefined ? { wangpProcessorSettings: settings as Record<string, unknown> | null } : {}),
      }
    },
    validate(action) {
      const validSource = Boolean(action.assetId || action.source)
      return action.confirm === true && validSource
        && (action.sourceKind === 'image' || action.sourceKind === 'video')
        && TOOLS_UPSCALE_METHODS.includes(action.method)
        ? []
        : ['an exact image/video source, source kind, installed method and confirmation are required']
    },
    async prepare(action) { return action },
    async execute(action, context) {
      return context.adapters.tools.upscale(action, context.generationContext)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'tool_job', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'studio', anchors: ['tools', 'upscale'], replay: 'atomic' },
  }
  register(upscaleDefinition)
}
