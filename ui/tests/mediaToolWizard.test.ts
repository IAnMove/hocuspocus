import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { executeMediaTool, mediaToolMessage } from '../src/features/agent/mediaToolCapabilities.ts'
import { wizardTrailTargets } from '../src/features/agent/wizardTrail.ts'
import { runRegisteredCapability } from '../src/features/agent/capabilityRunner.ts'

test('the Wizard saves the last frame of a clip through the media tools route', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('media_tool'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /media_tool/)
  const capability = getCapability('media_tool')!
  assert.equal(capability.resolve({ type: 'media_tool', operation: 'shell.run', input: {} }), null)
  const action = capability.resolve({ type: 'media_tool', operation: 'media.frame', input: { source: 'h3-ship.mp4', at: 'last' } })
  assert.deepEqual(action, { type: 'media_tool', operation: 'media.frame', input: { source: 'h3-ship.mp4', at: 'last' } })
  const sent: Array<{ url: string, body: Record<string, unknown>, headers?: unknown }> = []
  const previousFetch = globalThis.fetch
  Object.assign(globalThis, {
    fetch: async (url: string, init?: { body?: string, headers?: unknown }) => {
      sent.push({ url, body: JSON.parse(init?.body || '{}'), headers: init?.headers })
      return { ok: true, json: async () => ({ result: { file: 'h3-ship-frame-last.png', url: '/api/v1/file/h3-ship-frame-last.png?workspace=show' } }) }
    },
  })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const outcome = await capability.execute(action!, { adapters: createDefaultApplicationAdapters(), workspace: 'show',
      generationContext: { actor: 'wizard', commandId: 'wizard-frame-1' } })
    assert.deepEqual(sent, [{ url: '/api/v1/media/commands', headers: { 'content-type': 'application/json', 'X-Hocus-UI-Surface': 'wizard' }, body: {
      operation: 'media.frame', version: 1, intent_id: 'wizard-frame-1', input: { source: 'h3-ship.mp4', at: 'last', workspace: 'show' } } }])
    assert.equal(outcome.message, 'Fotograma guardado: h3-ship-frame-last.png.')
    assert.deepEqual(wizardTrailTargets({ state: 'completed', target: outcome.target, metadata: outcome.metadata }),
      [{ kind: 'file', id: 'h3-ship-frame-last.png', file: 'h3-ship-frame-last.png', title: 'media.frame' }])
  } finally {
    globalThis.fetch = previousFetch
  }
  assert.match(mediaToolMessage('studio.key', { result: { file: 'k.png', report: { haze: true, semiTransparentShare: 0.6 } } }),
    /velo en el 60 %/)
})

test('the runner uses one command identity for the media request, result and Wizard trail', async () => {
  const previousFetch = globalThis.fetch
  const sent: Array<{ url: string, body: Record<string, unknown> }> = []
  globalThis.fetch = (async (url, init) => {
    sent.push({ url: String(url), body: JSON.parse(String(init?.body)) })
    return new Response(JSON.stringify(String(url).endsWith('wizard-changes')
      ? { recorded: true } : { result: { file: 'frame.png' } }), { status: 200 })
  }) as typeof fetch
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const result = await runRegisteredCapability({ type: 'media_tool', operation: 'media.frame', input: { source: 'clip.mp4' } }, {
      adapters: createDefaultApplicationAdapters(), workspace: 'show',
      availability: { location: { tab: 'images' }, labs: {
        story: { project_id: '' }, series: { series_id: '', episode_id: '', shots: 0, approved: 0 },
      } },
    })
    await new Promise(resolve => setTimeout(resolve, 0))
    const command = sent.find(item => item.url.endsWith('/media/commands'))!.body
    const trail = sent.find(item => item.url.endsWith('/tasks/wizard-changes'))!.body
    assert.ok(command.intent_id)
    assert.equal(trail.commandId, command.intent_id)
    assert.deepEqual(trail.targets, [{ kind: 'file', id: 'frame.png', file: 'frame.png', title: 'media.frame' }])
    assert.equal(result?.commandResult?.commandId, command.intent_id)
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('a media action cannot publish into a workspace different from its command and trail', async () => {
  const previousFetch = globalThis.fetch
  const sent: Record<string, unknown>[] = []
  globalThis.fetch = (async (_url, init) => {
    sent.push(JSON.parse(String(init?.body)))
    return new Response(JSON.stringify({ result: { file: 'asset.glb' } }), { status: 200 })
  }) as typeof fetch
  try {
    await assert.rejects(executeMediaTool({ type: 'media_tool', operation: 'media.frame',
      input: { workspace: 'other', source: 'clip.mp4' } }, 'show', 'c1'), /espacio activo/)
    assert.equal(sent.length, 0)
    await executeMediaTool({ type: 'media_tool', operation: 'assets.import_from_workspace',
      input: { source_workspace: 'other', file: 'asset.glb' } }, 'show', 'c2')
    assert.deepEqual(sent[0].input, { source_workspace: 'other', file: 'asset.glb', workspace: 'show' })
  } finally {
    globalThis.fetch = previousFetch
  }
})
