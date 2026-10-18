import type { defineCapability } from './capabilityRegistry'

export const ROOM_SET_OPERATIONS = ['scene3d.room.put', 'scene3d.room.get'] as const

export type RoomSetOperation = typeof ROOM_SET_OPERATIONS[number]

export interface AgentRoomSetsAction {
  type: 'room_sets'
  operation: RoomSetOperation
  input: Record<string, unknown>
}

const operations = new Set<string>(ROOM_SET_OPERATIONS)
const registrars = new WeakSet<object>()

export function roomSetMessage(body: { result?: { name?: string; file?: string } }): string {
  const name = body.result?.name || 'room'
  const file = body.result?.file || ''
  return file ? `Stored room ${name} at ${file}.` : `Room ${name}.`
}

export function registerRoomSetCapabilities(register: typeof defineCapability) {
  if (registrars.has(register)) return
  registrars.add(register)
  register<AgentRoomSetsAction>({
    name: 'room_sets',
    title: 'Store a metric room',
    description: 'Store or read a metric box room (metres, open toward the camera) for a wide interior full-body shot. scene3d.room.put writes a placeholder; it does not paint textures.',
    useWhen: 'The user asks for an interior room at real size, with people standing on the floor.',
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
    risk: 'edit', confirmation: 'none', progress: 'Saving a metric room',
    resolve(raw) {
      if (typeof raw.operation !== 'string' || !operations.has(raw.operation) || !raw.input || typeof raw.input !== 'object' || Array.isArray(raw.input)) return null
      return { type: 'room_sets', operation: raw.operation as RoomSetOperation, input: raw.input as Record<string, unknown> }
    },
    validate(action) { return operations.has(action.operation) ? [] : ['Choose scene3d.room.put or scene3d.room.get.'] },
    async prepare(action) { return action },
    async execute(action, context) {
      const intent = action.operation === 'scene3d.room.put'
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
