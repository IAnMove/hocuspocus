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

test('remove-background adapter unquotes encoded source when submitting with asset_id', async () => {
  const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
  const { useStore } = await import('../src/stores/useStore.ts')
  const { clearExecutionMemory } = await import('../src/features/agent/agentContract.ts')
  const before = {
    mediaFilter: useStore.getState().mediaFilter,
    sidebarMode: useStore.getState().sidebarMode,
    sidebarOpen: useStore.getState().sidebarOpen,
    settingsOpen: useStore.getState().settingsOpen,
    dashboardOpen: useStore.getState().dashboardOpen,
    activeWorkspace: useStore.getState().activeWorkspace,
    toolsSourcePath: useStore.getState().toolsSourcePath,
    toolsSourceName: useStore.getState().toolsSourceName,
    toolsSourceAssetId: useStore.getState().toolsSourceAssetId,
  }
  const received = []
  const previousFetch = globalThis.fetch
  globalThis.fetch = async (input, init) => {
    const requestUrl = typeof input === 'string' ? input : input.url || String(input)
    if (requestUrl.includes('/api/v1/assets/asset_portrait')) {
      return new Response(JSON.stringify({
        id: 'asset_portrait',
        kind: 'image',
        filename: 'my portrait.png',
        size_bytes: 12,
        created_at: 1,
        completed_at: 2,
        metadata_status: 'canonical',
        workspace_ids: ['default'],
        locations: [{
          workspace_id: 'default',
          filename: 'my portrait.png',
          url: '/api/v1/file/my%20portrait.png?workspace=default',
        }],
        url: '/api/v1/file/my%20portrait.png?workspace=default',
        origin: { tool: 'studio' },
        execution: {},
        model: { provider: 'local', id: 'flux' },
        prompt_preview: 'portrait',
      }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    }
    if (requestUrl.includes('/api/v1/tools/remove-background')) {
      received.push(JSON.parse(init.body))
      return new Response(JSON.stringify({ job_id: 'job-portrait', task_id: 'job-portrait' }), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      })
    }
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  }
  clearExecutionMemory()
  useStore.setState({
    activeWorkspace: 'default',
    settingsOpen: false,
    dashboardOpen: false,
    sidebarMode: 'studio',
    sidebarOpen: false,
  })
  try {
    const adapters = createDefaultApplicationAdapters()
    const outcome = await adapters.tools.removeBackground({
      type: 'remove_background',
      assetId: 'asset_portrait',
      source: '/api/v1/file/my%20portrait.png',
      confirm: true,
    }, { actor: 'wizard', capability: 'remove_background', commandId: 'cmd-encoded' })
    assert.equal(received.length, 1)
    assert.equal(received[0].asset_id, 'asset_portrait')
    assert.equal(received[0].source, 'my portrait.png')
    assert.equal(received[0].source_workspace, 'default')
    assert.equal(useStore.getState().toolsSourcePath, 'my portrait.png')
    assert.equal(useStore.getState().toolsSourceName, 'my portrait.png')
    assert.equal(useStore.getState().toolsSourceAssetId, 'asset_portrait')
    assert.equal(outcome.taskId, 'job-portrait')
    assert.match(outcome.message, /my portrait\.png/)
  } finally {
    globalThis.fetch = previousFetch
    useStore.setState(before)
    clearExecutionMemory()
  }
})
