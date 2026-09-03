/** Capabilities for standalone post-processing tools. */
import type { CapabilityDefinition, defineCapability } from './capabilityRegistry'

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
export function registerToolCapabilities(register: typeof defineCapability): void {
  const registrar = register as unknown as object
  if (registeredRegistrars.has(registrar)) return
  registeredRegistrars.add(registrar)

  const definition: CapabilityDefinition<AgentRemoveBackgroundAction> = {
    name: 'remove_background',
    title: 'Remove image background',
    description: 'Open Tools and create a transparent derived image from an exact existing image asset.',
    useWhen: 'The user explicitly asks to remove, erase or make an image background transparent.',
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
    progress: 'Removing the image background…',
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
        : ['an exact image asset_id or source plus confirmation is required']
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
}
