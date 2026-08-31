import assert from 'node:assert/strict'
import test from 'node:test'

test('every AgentAction is registered exactly once in the common capability contract', async () => {
  const { AGENT_ACTION_TYPES } = await import('../src/features/agent/agentActionTypes.ts')
  const { listCapabilities } = await import('../src/features/agent/capabilityRegistry.ts')
  const registered = listCapabilities().map(capability => capability.name)

  assert.equal(new Set(AGENT_ACTION_TYPES).size, AGENT_ACTION_TYPES.length, 'duplicate action type in manifest')
  assert.equal(new Set(registered).size, registered.length, 'duplicate capability registration')
  assert.deepEqual(
    [...new Set(AGENT_ACTION_TYPES)].sort(),
    [...new Set(registered)].sort(),
    'AgentAction and capability registry must remain exhaustive',
  )
})
