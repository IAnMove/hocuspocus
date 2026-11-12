import assert from 'node:assert/strict'
import test from 'node:test'
import { realMakeInput } from '../src/api/realCharacter.ts'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { HOCUSPOCUS_AGENT_RESPONSE_SCHEMA, parseAgentTurn } from '../src/features/agent/agentActions.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'

test('"hazme un hombre realista con traje" is the server job the Studio 3D panel and model3d.real.make start', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('make_real_character'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /make_real_character/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /only outfit_prompt to change the clothes/)
  const properties = (HOCUSPOCUS_AGENT_RESPONSE_SCHEMA as { properties: { actions: { items: { properties: Record<string, unknown> } } } }).properties.actions.items.properties
  for (const key of ['name', 'gender', 'outfit_prompt', 'face_prompt', 'seed', 'talk_kit', 'confirm']) assert.ok(properties[key], key)
  // The merged schema keeps the first capability's spec of a shared key: it must still admit what this capability sends.
  const spec = (key: string) => properties[key] as { enum?: string[]; type?: string; minimum?: number; maximum?: number }
  for (const value of ['man', 'woman']) assert.ok(spec('gender').enum!.includes(value), value)
  assert.deepEqual(spec('bottom').enum, ['trousers', 'skirt', 'shorts'])
  assert.deepEqual(spec('body').enum, ['slim', 'average', 'tall'])
  assert.equal(spec('height_m').type, 'number', 'height is a picture size in pixels elsewhere: metres have a key of their own')
  assert.ok(spec('height_m').minimum! <= 1.2 && spec('height_m').maximum! >= 2.2)
  const capability = getCapability('make_real_character')!
  assert.equal(capability.risk, 'compute')
  assert.equal(capability.confirmation, 'required')
  assert.equal(capability.resolve({ type: 'make_real_character', name: 'Marta', outfit_prompt: 'a suit' }), null, 'minutes of GPU need the user\'s confirmation')
  assert.equal(capability.resolve({ type: 'make_real_character', name: ' ', confirm: true }), null)
  // The model fills the fields it does not use with empty values: they are left out, so a remake keeps the stored recipe.
  assert.deepEqual(capability.resolve({ type: 'make_real_character', name: 'Marta', gender: 'girl', skin: 'pink', height: '', body: '', outfit_prompt: ' A grey suit. ', face_prompt: '', seed: 3.5, confirm: true }),
    { type: 'make_real_character', name: 'Marta', confirm: true, outfitPrompt: 'A grey suit.' })
  assert.deepEqual(capability.resolve({ type: 'make_real_character', name: 'Marta', gender: 'woman', skin: '#e3b58f', height_m: 1.7, bottom: 'skirt', face_prompt: 'Red hair.', seed: 7, talk_kit: false, confirm: true }),
    { type: 'make_real_character', name: 'Marta', confirm: true, gender: 'woman', skin: '#E3B58F', height: 1.7, bottom: 'skirt', facePrompt: 'Red hair.', seed: 7, talkKit: false })
  assert.deepEqual(capability.resolve({ type: 'make_real_character', name: 'Marta', talk_kit: true, confirm: true }),
    { type: 'make_real_character', name: 'Marta', confirm: true, talkKit: true })
  const parsed = parseAgentTurn(JSON.stringify({ reply: 'Empiezo.', actions: [{ type: 'make_real_character', name: 'Marta', outfit_prompt: 'A suit.', confirm: true }] }))
  assert.equal(parsed.actions[0]?.type, 'make_real_character')

  const calls: Array<{ url: string; body?: Record<string, unknown> }> = []
  const previousFetch = globalThis.fetch
  Object.assign(globalThis, { fetch: async (url: string, init?: { body?: string }) => {
    calls.push({ url, ...(init?.body ? { body: JSON.parse(init.body) } : {}) })
    return { ok: true, json: async () => ({ version: 1, operation: 'model3d.real.make', status: 'running', result: { jobId: 'real-1', name: 'Marta', status: 'running', steps: [] } }) }
  } })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const action = capability.resolve({ type: 'make_real_character', name: 'Marta', outfit_prompt: 'A charcoal suit.', confirm: true })!
    const outcome = await capability.execute(action, { adapters: createDefaultApplicationAdapters(), workspace: 'show' })
    assert.equal(calls.length, 1)
    assert.equal(calls[0].url, '/api/v1/model3d/real')
    const body = calls[0].body as { version: number; intent_id: string; input: Record<string, unknown> }
    assert.equal(body.version, 1)
    assert.ok(body.intent_id)
    assert.deepEqual(body.input, { workspace: 'show', name: 'Marta', outfit_prompt: 'A charcoal suit.' }, 'only what changed: the server keeps the face, the seed and the rest')
    assert.match(outcome.message, /Empiezo a hacer a Marta|Starting Marta/)
    assert.equal(outcome.jobId, 'real-1')
    assert.deepEqual(outcome.target, { kind: 'output', id: 'real-1', title: 'Marta' })
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('the panel and the Wizard send the same input: only the fields given, prompts trimmed', () => {
  assert.deepEqual(realMakeInput({ workspace: 'w', name: 'Ana', gender: 'woman', outfitPrompt: '  A red hoodie. ', facePrompt: '', seed: 0, talkKit: true }),
    { workspace: 'w', name: 'Ana', gender: 'woman', outfit_prompt: 'A red hoodie.', seed: 0, talk_kit: true })
  assert.deepEqual(realMakeInput({ workspace: 'w', name: 'Ana' }), { workspace: 'w', name: 'Ana' })
})

test('the anime capability offers woman, which the anime make accepts', () => {
  const anime = getCapability('anime_make')!
  assert.equal((anime.resolve({ type: 'anime_make', name: 'Ana', gender: 'woman' }) as { gender?: string }).gender, 'woman')
})
