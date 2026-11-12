import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { shouldMountWorld3DScene, WORLD3D_TEMPLATE_OPERATIONS } from '../src/features/agent/world3dTemplateCapabilities.ts'

test('a blob face is a CPU wizard action and a scene mount', () => {
  assert.equal(AGENT_ACTION_TYPES.includes('make_character_face'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /make_character_face/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /world3d\.scene\.face/)
  const capability = getCapability('make_character_face')!
  assert.equal(capability.confirmation, 'none')
  assert.deepEqual(capability.resolve({ type: 'make_character_face', name: 'Walrus', traits: { eyes: 'dot', moustache: 'walrus' } }),
    { type: 'make_character_face', name: 'Walrus', traits: { eyes: 'dot', moustache: 'walrus' } })
  assert.equal(capability.resolve({ type: 'make_character_face' }), null)
  assert.equal(WORLD3D_TEMPLATE_OPERATIONS.includes('world3d.scene.face'), true)
  assert.equal(shouldMountWorld3DScene('world3d.scene.face'), true)
})
