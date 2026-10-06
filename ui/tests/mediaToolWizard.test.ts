import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { mediaToolMessage } from '../src/features/agent/mediaToolCapabilities.ts'

test('the Wizard saves the last frame of a clip through the media tools route', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('media_tool'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /media_tool/)
  const capability = getCapability('media_tool')!
  assert.equal(capability.resolve({ type: 'media_tool', operation: 'shell.run', input: {} }), null)
  const action = capability.resolve({ type: 'media_tool', operation: 'media.frame', input: { source: 'h3-ship.mp4', at: 'last' } })
  assert.deepEqual(action, { type: 'media_tool', operation: 'media.frame', input: { source: 'h3-ship.mp4', at: 'last' } })
  const sent: Array<{ url: string, body: Record<string, unknown> }> = []
  const previousFetch = globalThis.fetch
  Object.assign(globalThis, {
    fetch: async (url: string, init?: { body?: string }) => {
      sent.push({ url, body: JSON.parse(init?.body || '{}') })
      return { ok: true, json: async () => ({ result: { file: 'h3-ship-frame-last.png', url: '/api/v1/file/h3-ship-frame-last.png?workspace=show' } }) }
    },
  })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const outcome = await capability.execute(action!, { adapters: createDefaultApplicationAdapters(), workspace: 'show' })
    assert.deepEqual(sent, [{ url: '/api/v1/media/commands', body: {
      operation: 'media.frame', version: 1, input: { source: 'h3-ship.mp4', at: 'last', workspace: 'show' } } }])
    assert.equal(outcome.message, 'Fotograma guardado: h3-ship-frame-last.png.')
  } finally {
    globalThis.fetch = previousFetch
  }
  assert.match(mediaToolMessage('studio.key', { result: { file: 'k.png', report: { haze: true, semiTransparentShare: 0.6 } } }),
    /velo en el 60 %/)
})
