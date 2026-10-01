import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { productionWorksMessage } from '../src/features/agent/productionWorkCapabilities.ts'
import { REVIEW_EVENT } from '../src/features/production-catalog/reviewEvent.ts'

test('the wizard can list and open a production without treating a proposal as a new cut', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('production_works'), true)
  const capability = getCapability('production_works')
  assert.ok(capability)
  assert.equal(capability.resolve({ type: 'production_works', operation: 'production.review', input: { workspace: 'film' } }), null)
  const action = capability.resolve({ type: 'production_works', operation: 'production.works.open', input: { production_id: 'clip-mcp' } })
  assert.equal(action?.type, 'production_works')
  if (!action || action.type !== 'production_works') return
  const listed = productionWorksMessage({ applied: false, works: [{ production_id: 'clip-mcp', origin: 'mcp', project: { id: 'story-mcp' } }] })
  assert.match(listed, /clip-mcp/)
  assert.match(listed, new RegExp(REVIEW_EVENT))
  assert.doesNotMatch(listed, /Linked/)
  const kept = productionWorksMessage({
    applied: true, reused: true, production_id: 'clip-mcp',
    review: { event: REVIEW_EVENT, workspace: 'film', production_id: 'clip-mcp' },
  })
  assert.match(kept, /Kept clip-mcp/)
  assert.match(kept, /film/)

  const events: Array<{ type: string, detail: { workspace: string, productionId: string } }> = []
  const previousWindow = globalThis.window
  const previousFetch = globalThis.fetch
  Object.assign(globalThis, {
    window: { dispatchEvent(event: { type: string, detail: { workspace: string, productionId: string } }) { events.push(event); return true } },
    fetch: async () => ({
      ok: true,
      json: async () => ({
        applied: true,
        reused: false,
        production_id: 'clip-mcp',
        review: { event: REVIEW_EVENT, workspace: 'film', production_id: 'clip-mcp', project: { kind: 'story', id: 'story-mcp' } },
      }),
    }),
  })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const outcome = await capability.execute(action, { adapters: createDefaultApplicationAdapters(), workspace: 'film' })
    assert.match(outcome.message, /Linked clip-mcp/)
    assert.equal(events[0]?.type, REVIEW_EVENT)
    assert.deepEqual(events[0]?.detail, { workspace: 'film', productionId: 'clip-mcp' })
  } finally {
    globalThis.window = previousWindow
    globalThis.fetch = previousFetch
  }
})
