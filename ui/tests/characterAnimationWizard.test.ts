import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { HOCUSPOCUS_AGENT_RESPONSE_SCHEMA, parseAgentTurn } from '../src/features/agent/agentActions.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { findAnimationKit } from '../src/features/agent/characterAnimationCapabilities.ts'
import { createCharacterKit, emptyCharacterKitLibrary } from '../src/lib/characterKit.ts'

const base = { id: 'h-base', name: 'Hero', source: '/api/v1/file/h.png?workspace=show', kind: 'image' as const, alphaStatus: 'transparent' as const, reviewState: 'approved' as const }
const kits = { hero: { ...createCharacterKit('Heroína'), id: 'hero', base }, ines: { ...createCharacterKit('Inés'), id: 'ines', base } }

test('"hazle una cara de enfado a Heroína" is the same server job the Character Creator and the MCP tools start', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('make_character_animation'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /make_character_animation/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /angry, surprised/, 'the Wizard is told which animations exist, from the same catalog')
  const properties = (HOCUSPOCUS_AGENT_RESPONSE_SCHEMA as { properties: { actions: { items: { properties: Record<string, unknown> } } } }).properties.actions.items.properties
  for (const key of ['kit_name', 'animation_id', 'custom_animation', 'pose_id', 'confirm']) assert.ok(properties[key], key)
  const capability = getCapability('make_character_animation')!
  assert.equal(capability.risk, 'compute')
  assert.equal(capability.confirmation, 'required')
  assert.equal(capability.resolve({ type: 'make_character_animation', kit_name: 'Heroína', animation_id: 'angry' }), null, 'a GPU job of minutes needs the user\'s confirmation')
  assert.equal(capability.resolve({ type: 'make_character_animation', animation_id: 'Not A Slug!', confirm: true }), null)
  // The model fills the fields it does not use with empty values.
  assert.deepEqual(capability.resolve({ type: 'make_character_animation', kit_name: 'Heroína', animation_id: 'angry', custom_animation: {}, pose_id: '', confirm: true }),
    { type: 'make_character_animation', kitName: 'Heroína', animation: 'angry', confirm: true })
  assert.deepEqual(capability.resolve({ type: 'make_character_animation', animation_id: 'sonrisa-picara', confirm: true,
    custom_animation: { title: 'Sonrisa pícara', view: 'bust', poses: ['una sonrisa torcida', ' ', 'la misma con un guiño'] } }),
    { type: 'make_character_animation', kitName: '', animation: 'sonrisa-picara', confirm: true, custom: { title: 'Sonrisa pícara', view: 'bust', poses: ['una sonrisa torcida', 'la misma con un guiño'] } })
  assert.equal(capability.resolve({ type: 'make_character_animation', animation_id: 'x', confirm: true, custom_animation: { title: 'T', view: 'wide', poses: ['a'] } }), null, 'a view the server does not know')
  assert.equal(capability.resolve({ type: 'make_character_animation', animation_id: 'x', confirm: true, custom_animation: { title: 'T', view: 'bust', poses: Array(7).fill('a') } }), null, 'more poses than a sheet takes')
  assert.deepEqual(capability.validate({ type: 'make_character_animation', kitName: '', animation: 'wave', confirm: true, custom: { title: 'T', view: 'bust', poses: ['a'] } }),
    ['wave is in the catalog: leave custom out'])
  const parsed = parseAgentTurn(JSON.stringify({ reply: 'Empiezo.', actions: [{ type: 'make_character_animation', kit_name: 'Heroína', animation_id: 'wave', confirm: true }] }))
  assert.equal(parsed.actions[0]?.type, 'make_character_animation')

  const calls: Array<{ url: string; body?: Record<string, unknown> }> = []
  const previousFetch = globalThis.fetch
  Object.assign(globalThis, { fetch: async (url: string, init?: { body?: string }) => {
    calls.push({ url, ...(init?.body ? { body: JSON.parse(init.body) } : {}) })
    if (url.includes('/animations/make')) return { ok: true, json: async () => ({ job: { jobId: 'anim-1', status: 'running', title: 'Angry', takes: [{ id: 'a' }, { id: 'b' }] } }) }
    return { ok: true, json: async () => ({ ...emptyCharacterKitLibrary(), revision: 2, activeId: 'ines', kits }) }
  } })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const action = capability.resolve({ type: 'make_character_animation', kit_name: 'heroína', animation_id: 'angry', confirm: true })!
    const outcome = await capability.execute(action, { adapters: createDefaultApplicationAdapters(), workspace: 'show' })
    assert.equal(calls[0].url, '/api/v1/character-kits/library?workspace=show')
    assert.equal(calls[1].url, '/api/v1/character-kits/animations/make')
    assert.deepEqual(calls[1].body, { workspace: 'show', kitId: 'hero', animation: 'angry' }, 'the same request the panel and characters.animation.make send')
    assert.match(outcome.message, /Empiezo la animación|Starting the/)
    assert.match(outcome.message, /Heroína/)
    assert.equal(outcome.jobId, 'anim-1')
    assert.deepEqual(outcome.target, { kind: 'character_kit', id: 'hero', title: 'Heroína' })
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('the character is found by name or id, or is the only or the active one, and the Wizard says who it can choose', () => {
  assert.equal(findAnimationKit(kits, 'ines', 'inés').id, 'ines')
  assert.equal(findAnimationKit(kits, 'ines', 'hero').id, 'hero')
  assert.equal(findAnimationKit(kits, 'ines', '').id, 'ines', 'with two, the active one')
  assert.equal(findAnimationKit({ hero: kits.hero }, undefined, '').id, 'hero', 'with one, that one')
  assert.throws(() => findAnimationKit(kits, 'ines', 'Zoe'), /no character called “Zoe”.*Heroína, Inés/)
  assert.throws(() => findAnimationKit(kits, undefined, ''), /Say which character: Heroína, Inés/)
  assert.throws(() => findAnimationKit({}, undefined, ''), /Create one in Character Creator first|create one in Character Creator first/i)
})
