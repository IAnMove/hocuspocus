import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes'
import { registerWorld3DTemplateCapabilities, world3dTemplateMessage } from '../src/features/agent/world3dTemplateCapabilities'

test('wizard capability sends the query and shows the real cards', async () => {
  let registered = 0
  let capability: { resolve: (raw: Record<string, unknown>) => { operation: string, input: Record<string, unknown> } | null, execute: (action: { operation: string, input: Record<string, unknown> }, context: { workspace: string, adapters: { world3dTemplates: { command: (action: { input: Record<string, unknown> }, workspace: string) => Promise<{ message: string }> } } }) => Promise<{ message: string }> } | undefined
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
  let seen = { query: '', workspace: '' }
  const outcome = await stored.execute(action, { workspace: 'studio', adapters: { world3dTemplates: { command: async (got, workspace) => {
    seen = { query: String(got.input.query), workspace }
    return { message: world3dTemplateMessage({ status: 'completed', result: { chosenId: 'cine-dolly-zoom', scene: { sceneId: 'w3d-abc', revision: 1 }, candidates: [{ id: 'cine-dolly-zoom', titleEs: 'Dolly Zoom', titleEn: 'Dolly zoom', format: 'landscape', duration: 5 }] } }) }
  } } } })
  assert.equal(seen.query, 'dolly zoom')
  assert.equal(seen.workspace, 'studio')
  assert.match(outcome.message, /cine-dolly-zoom/)
  const choice = world3dTemplateMessage({ status: 'needs_choice', result: { candidates: [{ id: 'cine-orbit-360', titleEs: 'Órbita de 360 grados', titleEn: '360-Degree Orbit', format: 'landscape', duration: 8 }, { id: 'product-orbit', titleEs: 'Órbita de producto', titleEn: 'Product orbit', format: 'landscape', duration: 6 }] } })
  assert.match(choice, /cine-orbit-360/)
  assert.match(choice, /Elige un id exacto/)
  assert.equal(world3dTemplateMessage({ status: 'not_found', result: { candidates: [] } }), 'Ninguna toma coincide con la búsqueda.')
})
