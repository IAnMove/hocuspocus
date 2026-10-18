import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes'
import { registerRoomSetCapabilities, roomSetMessage } from '../src/features/agent/roomSetsCapabilities'

test('wizard capability stores a room through the shared command and does not open an editor', async () => {
  let registered = 0
  let capability: {
    progress: string
    resolve: (raw: Record<string, unknown>) => { operation: string, input: Record<string, unknown> } | null
    execute: (action: { operation: string, input: Record<string, unknown> }, context: {
      workspace: string
      generationContext?: { commandId: string }
      adapters: { roomSets: { command: (action: { operation: string, input: Record<string, unknown> }, workspace: string) => Promise<{ message: string }> } }
    }) => Promise<{ message: string }>
  } | undefined
  const register = (item: NonNullable<typeof capability>) => { registered += 1; capability = item }
  registerRoomSetCapabilities(register as never)
  registerRoomSetCapabilities(register as never)
  assert.equal(registered, 1)
  assert.equal(AGENT_ACTION_TYPES.includes('room_sets'), true)
  const stored = capability
  if (!stored) throw new Error('capability was not registered')
  assert.equal(stored.progress.startsWith('wizard:'), false)
  assert.equal(stored.resolve({ type: 'room_sets', operation: 'scene3d.room.delete', input: { name: 'kitchen' } }), null)
  const action = stored.resolve({ type: 'room_sets', operation: 'scene3d.room.put', input: { name: 'kitchen', room: { kind: 'room' } } })
  if (!action) throw new Error('put did not resolve')
  let seen = { operation: '', workspace: '', intent: '' }
  const outcome = await stored.execute(action, {
    workspace: 'studio',
    generationContext: { commandId: 'wizard-room-1' },
    adapters: { roomSets: { command: async (got, workspace) => {
      seen = { operation: got.operation, workspace, intent: String(got.input.intent_id || '') }
      return { message: roomSetMessage({ result: { name: 'kitchen', file: 'rooms/kitchen.glb' } }) }
    } } },
  })
  assert.equal(seen.operation, 'scene3d.room.put')
  assert.equal(seen.workspace, 'studio')
  assert.equal(seen.intent, 'wizard-room-1')
  assert.match(outcome.message, /rooms\/kitchen\.glb/)
  const read = stored.resolve({ type: 'room_sets', operation: 'scene3d.room.get', input: { name: 'kitchen' } })
  if (!read) throw new Error('get did not resolve')
  let getIntent = false
  await stored.execute(read, {
    workspace: 'studio',
    adapters: { roomSets: { command: async got => {
      getIntent = 'intent_id' in got.input
      return { message: 'Room kitchen.' }
    } } },
  })
  assert.equal(getIntent, false)
})
