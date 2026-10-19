import type { defineCapability } from './capabilityRegistry'

export const ROOM_SET_OPERATIONS = ['scene3d.room.put', 'scene3d.room.get', 'scene3d.room.paint', 'scene3d.room.paint.status'] as const

export type RoomSetOperation = typeof ROOM_SET_OPERATIONS[number]

export interface AgentRoomSetsAction {
  type: 'room_sets'
  operation: RoomSetOperation
  input: Record<string, unknown>
}

const operations = new Set<string>(ROOM_SET_OPERATIONS)
// What changes a room takes a new intent id; the reads do not.
const mutations = new Set<string>(['scene3d.room.put', 'scene3d.room.paint'])
const registrars = new WeakSet<object>()

export function roomSetMessage(body: { result?: { name?: string; file?: string; status?: string; paint?: { status?: string }; warnings?: unknown[] } }, operation = ''): string {
  const name = body.result?.name || 'room'
  if (operation.startsWith('scene3d.room.paint')) {
    const status = body.result?.status || body.result?.paint?.status || 'queued'
    const warned = body.result?.warnings?.length ? `, ${body.result.warnings.length} warning(s)` : ''
    return `Room ${name} paint: ${status}${warned}.`
  }
  const file = body.result?.file || ''
  return file ? `Stored room ${name} at ${file}.` : `Room ${name}.`
}

export function registerRoomSetCapabilities(register: typeof defineCapability) {
  if (registrars.has(register)) return
  registrars.add(register)
  register<AgentRoomSetsAction>({
    name: 'room_sets',
    title: 'Store and paint a metric room',
    description: 'Store, read or paint a metric box room (metres, open toward the camera) for a wide interior full-body shot. scene3d.room.put stores it already textured with procedural materials; scene3d.room.paint repaints it with the image model in the background (poll scene3d.room.paint.status); a surface the model cannot paint keeps its procedural material.',
    useWhen: 'The user asks for an interior room at real size, with people standing on the floor, or for its walls, floor and door to look like something.',
    parameters: ['operation', 'input'],
    inputSchema: {
      type: 'object', additionalProperties: false,
      properties: {
        type: { const: 'room_sets' },
        operation: { enum: [...ROOM_SET_OPERATIONS] },
        input: { type: 'object' },
      },
      required: ['type', 'operation', 'input'],
    },
    risk: 'edit', confirmation: 'none', progress: 'Saving or painting a metric room',
    resolve(raw) {
      if (typeof raw.operation !== 'string' || !operations.has(raw.operation) || !raw.input || typeof raw.input !== 'object' || Array.isArray(raw.input)) return null
      return { type: 'room_sets', operation: raw.operation as RoomSetOperation, input: raw.input as Record<string, unknown> }
    },
    validate(action) { return operations.has(action.operation) ? [] : ['Choose scene3d.room.put, get, paint or paint.status.'] },
    async prepare(action) { return action },
    async execute(action, context) {
      const intent = mutations.has(action.operation)
        ? (typeof action.input.intent_id === 'string' ? action.input.intent_id : context.generationContext?.commandId)
        : undefined
      const input = intent ? { ...action.input, intent_id: intent } : { ...action.input }
      return context.adapters.roomSets.command({ ...action, input }, context.workspace)
    },
    correlate(_action, outcome) { return outcome.target },
    async track(_action, outcome) { return outcome },
    report: { targetKind: 'video_3d_scene', successState: 'completed' },
    summarize(_action, outcome) { return outcome.message },
    presentation: { destination: 'video_3d', anchors: ['scene'], replay: 'atomic' },
  })
}
