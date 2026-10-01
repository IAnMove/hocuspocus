import type { defineCapability } from './capabilityRegistry'

export const WORLD3D_TEMPLATE_OPERATIONS = [
  'world3d.templates.list',
  'world3d.templates.catalog',
  'world3d.templates.get',
  'world3d.templates.user.put',
  'world3d.scene.instantiate',
  'world3d.scene.inspect',
  'world3d.scene.patch',
  'world3d.scene.preview',
  'world3d.scene.publish',
  'world3d.scene.apply_query',
] as const

export type World3DTemplateOperation = typeof WORLD3D_TEMPLATE_OPERATIONS[number]

/** Only these replies should replace the open Video 3D editor. Inspect/publish
 *  also return `scene.document`, but remounting them drops unsaved local edits. */
const MOUNT_SCENE_OPERATIONS = new Set<string>([
  'world3d.scene.instantiate',
  'world3d.scene.apply_query',
  'world3d.scene.patch',
])

export function shouldMountWorld3DScene(operation: string): boolean {
  return MOUNT_SCENE_OPERATIONS.has(operation)
}

export interface AgentWorld3DTemplatesAction {
  type: 'world3d_templates'
  operation: World3DTemplateOperation
  input: Record<string, unknown>
}

const operations = new Set<string>(WORLD3D_TEMPLATE_OPERATIONS)
const registrars = new WeakSet<object>()

export function world3dTemplateMessage(body: { status?: string; result?: Record<string, unknown> }): string {
  const result = body.result || {}
  const cards = (Array.isArray(result.candidates) ? result.candidates : Array.isArray(result.templates) ? result.templates : []) as Array<Record<string, unknown>>
  const lines = cards.slice(0, 8).map(card => `${card.id} | ${card.titleEs} | ${card.titleEn} | ${card.format} | ${card.duration}s`).join('\n')
  const scene = result.scene as { sceneId?: string; revision?: number } | undefined
  const chosen = typeof result.chosenId === 'string' ? result.chosenId : ''
  if (body.status === 'needs_choice' || result.status === 'needs_choice') return `Hay varias tomas. Elige un id exacto.\n${lines}`
  if (body.status === 'not_found' || result.status === 'not_found') return 'Ninguna toma coincide con la búsqueda.'
  if (chosen) return `Toma ${chosen}. Escena ${scene?.sceneId || ''} revisión ${scene?.revision ?? ''}.\n${lines}`
  if (lines) return lines
  return `Vídeo 3D ${scene?.sceneId || body.status || 'listo'}`
}

export function registerWorld3DTemplateCapabilities(register: typeof defineCapability) {
  if (registrars.has(register)) return
  registrars.add(register)
  register<AgentWorld3DTemplatesAction>({
    name: 'world3d_templates',
    title: 'Search and edit Video 3D shots',
    description: 'Search the existing Video 3D shot library, open an exact id, bind workspace resources by object id, preview the modified revision, and save it. apply_query instantiates only a uniquely top-ranked real id. Never invent a template id.',
    useWhen: 'The user asks to find, apply, or adapt a Video 3D shot, camera move, or scenario.',
    parameters: ['operation', 'input'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'world3d_templates' },
        operation: { enum: [...WORLD3D_TEMPLATE_OPERATIONS] },
        input: { type: 'object' },
      },
      required: ['type', 'operation', 'input'],
    },
    risk: 'edit', confirmation: 'none', progress: 'Buscando tomas de Vídeo 3D…',
    resolve(raw) {
      if (typeof raw.operation !== 'string' || !operations.has(raw.operation) || !raw.input || typeof raw.input !== 'object' || Array.isArray(raw.input)) return null
      return { type: 'world3d_templates', operation: raw.operation as World3DTemplateOperation, input: raw.input as Record<string, unknown> }
    },
    validate(action) { return operations.has(action.operation) ? [] : ['Choose a Video 3D template operation.'] },
    async prepare(action) { return action },
    async execute(action, context) { return context.adapters.world3dTemplates.command(action, context.workspace) },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_3d_scene', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_3d', anchors: ['scene'], replay: 'atomic' },
  })
}
