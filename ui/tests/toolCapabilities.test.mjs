import assert from 'node:assert/strict'
import test from 'node:test'

async function registeredToolCapabilities() {
  const { registerToolCapabilities } = await import('../src/features/agent/toolCapabilities.ts')
  const definitions = []
  registerToolCapabilities(definition => {
    definitions.push(definition)
    return definition
  })
  return new Map(definitions.map(definition => [definition.name, definition]))
}

test('remove-background capability requires an exact source and explicit confirmation', async () => {
  const definition = (await registeredToolCapabilities()).get('remove_background')
  assert.equal(definition.inputSchema.additionalProperties, false)
  assert.deepEqual(definition.resolve({
    type: 'remove_background', asset_id: 'asset_image_123', source_workspace: 'default',
    instruction: 'preserve hair edges', confirm: true,
  }), {
    type: 'remove_background', assetId: 'asset_image_123', source: '', sourceWorkspace: 'default',
    instruction: 'preserve hair edges', confirm: true,
  })
  assert.equal(definition.resolve({ type: 'remove_background', asset_id: 'asset_image_123', confirm: false }), null)
  assert.equal(definition.resolve({ type: 'remove_background', confirm: true }), null)
  assert.deepEqual(definition.validate({
    type: 'remove_background', assetId: 'asset_image_123', source: '', confirm: true,
  }), [])
  assert.notDeepEqual(definition.validate({
    type: 'remove_background', assetId: '', source: '', confirm: true,
  }), [])
})
test('remove-background execution is delegated to the Tools application adapter', async () => {
  const definition = (await registeredToolCapabilities()).get('remove_background')
  const action = { type: 'remove_background', assetId: 'asset_image_123', source: '', confirm: true }
  const calls = []
  const outcome = await definition.execute(action, {
    workspace: 'default',
    generationContext: { actor: 'wizard', capability: 'remove_background', commandId: 'cmd-1' },
    adapters: {
      tools: {
        removeBackground: async (received, context) => {
          calls.push({ received, context })
          return { message: 'queued', target: { kind: 'tool_job', id: 'job-1', title: 'Remove background' }, taskId: 'job-1' }
        },
      },
    },
  })
  assert.equal(outcome.taskId, 'job-1')
  assert.deepEqual(calls, [{ received: action, context: { actor: 'wizard', capability: 'remove_background', commandId: 'cmd-1' } }])
})
