import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes'
import {
  registerWorld3DTemplateCapabilities,
  world3dTemplateCommandIntent,
  world3dTemplateMessage,
} from '../src/features/agent/world3dTemplateCapabilities'

test('wizard capability sends the query and shows the real cards', async () => {
  let registered = 0
  let capability: { resolve: (raw: Record<string, unknown>) => { operation: string, input: Record<string, unknown> } | null, execute: (action: { operation: string, input: Record<string, unknown> }, context: { workspace: string, generationContext?: { actor: 'wizard', commandId: string }, adapters: { world3dTemplates: { command: (action: { input: Record<string, unknown> }, workspace: string) => Promise<{ message: string }> } } }) => Promise<{ message: string }> } | undefined
  const register = (item: NonNullable<typeof capability>) => { registered += 1; capability = item }
  registerWorld3DTemplateCapabilities(register as never)
  registerWorld3DTemplateCapabilities(register as never)
  assert.equal(registered, 1)
  assert.equal(AGENT_ACTION_TYPES.includes('world3d_templates'), true)
  const stored = capability
  if (!stored) throw new Error('capability was not registered')
  assert.equal(stored.resolve({ type: 'world3d_templates', operation: 'nope', input: { query: 'dolly zoom' } }), null)
  assert.equal(stored.resolve({ type: 'world3d_templates', operation: 'world3d.scene.apply_query', input: [] }), null)
  const action = stored.resolve({ type: 'world3d_templates', operation: 'world3d.scene.apply_query', input: { query: 'dolly zoom' } })
  if (!action) throw new Error('apply_query did not resolve')
  assert.equal(action.operation, 'world3d.scene.apply_query')
  assert.equal('template_id' in action.input, false)
  assert.equal(JSON.stringify(action).includes('cine-dolly-zoom'), false)
  let seen = { query: '', workspace: '', intent: '' }
  const outcome = await stored.execute(action, {
    workspace: 'studio',
    generationContext: { actor: 'wizard', commandId: 'wizard-cmd-dolly-1' },
    adapters: { world3dTemplates: { command: async (got, workspace) => {
      seen = { query: String(got.input.query), workspace, intent: String(got.input.intent_id || '') }
      return { message: world3dTemplateMessage({ status: 'completed', result: { chosenId: 'cine-dolly-zoom', scene: { sceneId: 'w3d-abc', revision: 1 }, candidates: [{ id: 'cine-dolly-zoom', titleEs: 'Dolly Zoom', titleEn: 'Dolly zoom', format: 'landscape', duration: 5 }] } }) }
    } } },
  })
  assert.equal(seen.query, 'dolly zoom')
  assert.equal(seen.workspace, 'studio')
  assert.equal(seen.intent, 'wizard-cmd-dolly-1')
  assert.match(outcome.message, /cine-dolly-zoom/)
  const choice = world3dTemplateMessage({ status: 'needs_choice', result: { candidates: [{ id: 'cine-orbit-360', titleEs: 'Órbita de 360 grados', titleEn: '360-Degree Orbit', format: 'landscape', duration: 8 }, { id: 'product-orbit', titleEs: 'Órbita de producto', titleEn: 'Product orbit', format: 'landscape', duration: 6 }] } })
  assert.match(choice, /cine-orbit-360/)
  assert.match(choice, /Elige un id exacto/)
  assert.equal(world3dTemplateMessage({ status: 'not_found', result: { candidates: [] } }), 'Ninguna toma coincide con la búsqueda.')
})

test('wizard mutations mint an intent_id and searches stay read-only', () => {
  assert.equal(world3dTemplateCommandIntent('world3d.templates.list', { query: 'dolly zoom' }), undefined)
  assert.equal(world3dTemplateCommandIntent('world3d.scene.inspect', { scene_id: 'w3d-abc' }), undefined)
  assert.equal(world3dTemplateCommandIntent('world3d.scene.preview', { scene_id: 'w3d-abc' }), undefined)
  assert.equal(
    world3dTemplateCommandIntent('world3d.scene.apply_query', { query: 'dolly zoom' }, 'wizard-cmd-1'),
    'wizard-cmd-1',
  )
  assert.equal(
    world3dTemplateCommandIntent('world3d.scene.patch', { intent_id: 'kept-intent', scene_id: 'w3d-abc' }, 'ignored'),
    'kept-intent',
  )
  const minted = world3dTemplateCommandIntent('world3d.scene.instantiate', { template_id: 'cine-dolly-zoom' })
  assert.match(String(minted), /^wizard-world3d-[A-Za-z0-9._:-]+$/)
  assert.equal(world3dTemplateCommandIntent('world3d.scene.publish', { intent_id: 'bad id' }, 'fallback-id'), 'fallback-id')
})
