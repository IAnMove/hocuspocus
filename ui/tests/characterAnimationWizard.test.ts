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
  assert.equal(capability.resolve({ type: 'make_character_animation', animation_id: 'x', confirm: true, custom_animation: { title: 'T', view: 'bust', poses: Array(13).fill('a') } }), null, 'more poses than a sheet takes')
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

test('the Wizard reviews an animation through the same route as characters.animation.review, and the server decides whether the mode allows it', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('review_character_animation'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /review_character_animation/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /Modo un solo disparo/, 'the Wizard is told it approves only in one-shot mode')
  const properties = (HOCUSPOCUS_AGENT_RESPONSE_SCHEMA as { properties: { actions: { items: { properties: Record<string, unknown> } } } }).properties.actions.items.properties
  for (const key of ['kit_name', 'animation_id', 'decision', 'note', 'auto_approve']) assert.ok(properties[key], key)
  const review = getCapability('review_character_animation')!
  assert.equal(review.risk, 'edit')
  assert.equal(review.confirmation, 'none', 'the mode is the owner\'s consent; the server refuses without it')
  assert.equal(review.resolve({ type: 'review_character_animation', animation_id: 'walk', decision: 'maybe' }), null)
  assert.equal(review.resolve({ type: 'review_character_animation', animation_id: 'Not A Slug!', decision: 'approve' }), null)
  assert.deepEqual(review.resolve({ type: 'review_character_animation', kit_name: 'Heroína', animation_id: 'Walk', decision: 'reject', note: ' la mano no se ve ' }),
    { type: 'review_character_animation', kitName: 'Heroína', animation: 'walk', decision: 'reject', note: 'la mano no se ve' })
  const make = getCapability('make_character_animation')!
  assert.deepEqual(make.resolve({ type: 'make_character_animation', animation_id: 'walk', auto_approve: true, confirm: true }),
    { type: 'make_character_animation', kitName: '', animation: 'walk', confirm: true, autoApprove: true })
  assert.deepEqual(make.resolve({ type: 'make_character_animation', animation_id: 'walk', auto_approve: false, confirm: true }),
    { type: 'make_character_animation', kitName: '', animation: 'walk', confirm: true }, 'approval is asked for, never assumed')

  const calls: Array<{ url: string; body?: Record<string, unknown> }> = []
  let mode: 'one_shot' | 'review' = 'one_shot'
  const previousFetch = globalThis.fetch
  Object.assign(globalThis, { fetch: async (url: string, init?: { body?: string }) => {
    calls.push({ url, ...(init?.body ? { body: JSON.parse(init.body) } : {}) })
    if (url.includes('/animations/review')) {
      return mode === 'one_shot'
        ? { ok: true, json: async () => ({ review: { kitId: 'hero', animation: 'walk', reviewState: 'approved', reviewedBy: 'agent', reviewedAt: 'now', reviewNote: 'ok', revision: 3 } }) }
        : { ok: false, json: async () => ({ detail: { code: 'agent_review_off', message: 'Agent review is off (agent_autonomy is review): apruébala en Personajes › Animaciones' } }) }
    }
    if (url.includes('/animations/make')) {
      return { ok: true, json: async () => ({ job: { jobId: 'anim-9', status: 'running', title: 'Walk', takes: [{ id: 'a' }], autoApprove: mode === 'one_shot',
        ...(mode === 'review' ? { autoApproveNote: 'autoApprove was ignored: agent_autonomy is review' } : {}) } }) }
    }
    return { ok: true, json: async () => ({ ...emptyCharacterKitLibrary(), revision: 2, activeId: 'ines', kits }) }
  } })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const context = { adapters: createDefaultApplicationAdapters(), workspace: 'show' }
    const action = review.resolve({ type: 'review_character_animation', kit_name: 'heroína', animation_id: 'walk', decision: 'approve', note: 'ok' })!
    const outcome = await review.execute(action, context)
    const posted = calls.find(call => call.url.includes('/animations/review'))!
    assert.equal(posted.url, '/api/v1/character-kits/animations/review')
    assert.deepEqual(posted.body, { workspace: 'show', kitId: 'hero', animation: 'walk', decision: 'approve', note: 'ok' }, 'the body characters.animation.review sends')
    assert.match(outcome.message, /aprobado|approved/i)
    assert.deepEqual(outcome.target, { kind: 'character_kit', id: 'hero', title: 'Heroína' })
    const asked = make.resolve({ type: 'make_character_animation', kit_name: 'heroína', animation_id: 'walk', auto_approve: true, confirm: true })!
    await make.execute(asked, context)
    assert.deepEqual(calls.filter(call => call.url.includes('/animations/make')).at(-1)!.body, { workspace: 'show', kitId: 'hero', animation: 'walk', autoApprove: true })
    mode = 'review'
    await assert.rejects(review.execute(action, context), /Agent review is off.*Personajes › Animaciones/s, 'review mode: the person reads what to do instead')
    const ignored = await make.execute(asked, context)
    assert.match(ignored.message, /autoApprove was ignored: agent_autonomy is review/, 'the person is told the approval stays theirs')
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('the Wizard makes the full walks as one server job through the route of the panel and characters.animation.make_set', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('make_character_animation_set'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /make_character_animation_set/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /walk-directions/)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /view bust\|front\|side\|front34\|back34\|back, poses: one description per pose, up to 12/, 'a custom animation takes twelve poses in any direction now')
  const properties = (HOCUSPOCUS_AGENT_RESPONSE_SCHEMA as { properties: { actions: { items: { properties: Record<string, unknown> } } } }).properties.actions.items.properties
  assert.ok(properties.set)
  const make = getCapability('make_character_animation_set')!
  assert.equal(make.risk, 'compute')
  assert.equal(make.confirmation, 'required', 'a job of many minutes of GPU')
  assert.equal(make.resolve({ type: 'make_character_animation_set', set: 'walk-directions' }), null, 'no confirmation')
  assert.equal(make.resolve({ type: 'make_character_animation_set', set: 'dance-all', confirm: true }), null)
  assert.deepEqual(make.resolve({ type: 'make_character_animation_set', kit_name: 'heroína', set: 'Walk-Directions', auto_approve: true, confirm: true }),
    { type: 'make_character_animation_set', kitName: 'heroína', set: 'walk-directions', confirm: true, autoApprove: true })
  assert.deepEqual(make.resolve({ type: 'make_character_animation_set', set: 'walk-12', auto_approve: false, confirm: true }),
    { type: 'make_character_animation_set', kitName: '', set: 'walk-12', confirm: true }, 'approval is asked for, never assumed')

  const calls: Array<{ url: string; body?: Record<string, unknown> }> = []
  let reply: Record<string, unknown> = { jobId: 'animset-1', status: 'running', sheets: [{ animationId: 'walk-12', status: 'running' }, { animationId: 'walk-front34', status: 'waiting' }, { animationId: 'walk-front', status: 'skipped' }] }
  const previousFetch = globalThis.fetch
  Object.assign(globalThis, { fetch: async (url: string, init?: { body?: string }) => {
    calls.push({ url, ...(init?.body ? { body: JSON.parse(init.body) } : {}) })
    if (url.includes('/animations/make-set')) return { ok: true, json: async () => ({ job: reply }) }
    return { ok: true, json: async () => ({ ...emptyCharacterKitLibrary(), revision: 2, activeId: 'ines', kits }) }
  } })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const context = { adapters: createDefaultApplicationAdapters(), workspace: 'show' }
    const action = make.resolve({ type: 'make_character_animation_set', kit_name: 'heroína', set: 'walk-directions', auto_approve: true, confirm: true })!
    const outcome = await make.execute(action, context)
    assert.equal(calls[0].url, '/api/v1/character-kits/library?workspace=show')
    assert.equal(calls[1].url, '/api/v1/character-kits/animations/make-set')
    assert.deepEqual(calls[1].body, { workspace: 'show', kitId: 'hero', set: 'walk-directions', autoApprove: true }, 'the same request the panel and characters.animation.make_set send')
    assert.match(outcome.message, /Heroína/)
    assert.match(outcome.message, /2 hojas|2 sheets/, 'the sheets still to make, not the ones the character has')
    assert.equal(outcome.jobId, 'animset-1')
    assert.deepEqual(outcome.target, { kind: 'character_kit', id: 'hero', title: 'Heroína' })
    reply = { jobId: 'animset-2', status: 'completed', sheets: [{ animationId: 'walk-12', status: 'skipped' }] }
    assert.match((await make.execute(make.resolve({ type: 'make_character_animation_set', kit_name: 'heroína', set: 'walk-12', confirm: true })!, context)).message, /ya tiene|already has/)
    reply = { jobId: 'animset-3', status: 'running', autoApprove: false, autoApproveNote: 'autoApprove was ignored: agent_autonomy is review', sheets: [{ animationId: 'walk-12', status: 'running' }] }
    assert.match((await make.execute(action, context)).message, /autoApprove was ignored: agent_autonomy is review/)
  } finally {
    globalThis.fetch = previousFetch
  }
})
