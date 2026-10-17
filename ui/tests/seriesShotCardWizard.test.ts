import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { HOCUSPOCUS_AGENT_RESPONSE_SCHEMA, parseAgentTurn } from '../src/features/agent/agentActions.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { cardBody, cardMessage, executeApplySeriesShotCard } from '../src/features/agent/seriesShotCardCapabilities.ts'
import { useSeriesStore } from '../src/features/series/store.ts'

type Call = { url: string, body: Record<string, unknown>, headers?: Record<string, string> }

const CAST = [{ slot: 'subject_1', characterId: 'gloria', animation: 'walk' }]

function seriesOpen() {
  useSeriesStore.setState({ workspace: 'show', activeSeriesId: 'pu', activeEpisodeId: 'ep1', saveNow: async () => null, reload: async () => undefined })
}

test('"pon la tarjeta de andar en el plano 3" is one registered action with the MCP tool\'s fields', () => {
  assert.equal(AGENT_ACTION_TYPES.includes('apply_series_shot_card'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /apply_series_shot_card/)
  const properties = (HOCUSPOCUS_AGENT_RESPONSE_SCHEMA as { properties: { actions: { items: { properties: Record<string, unknown> } } } })
    .properties.actions.items.properties
  for (const key of ['shot_number', 'shot_id', 'card_id', 'card_cast', 'card_controls', 'card_assets', 'approve_take']) assert.ok(properties[key], key)
  const capability = getCapability('apply_series_shot_card')!
  assert.equal(capability.risk, 'edit')
  assert.equal(capability.confirmation, 'none')
  // The model fills the fields it does not use with 0, "" and {}: those name nothing.
  assert.equal(capability.resolve({ type: 'apply_series_shot_card', shot_number: 0, shot_id: '', card_id: 'walk-cycle-sheet' }), null, 'no shot')
  assert.equal(capability.resolve({ type: 'apply_series_shot_card', shot_number: 3, card_id: '' }), null, 'no card')
  assert.equal(capability.resolve({ type: 'apply_series_shot_card', shot_number: 3, card_id: 'Walk Cycle!' }), null, 'not a card id')
  assert.deepEqual(capability.resolve({ type: 'apply_series_shot_card', series_id: '', episode_id: '', shot_number: 3, shot_id: '', card_id: 'Walk-Cycle-Sheet',
                                       card_cast: [{ slot: '', characterId: 'gloria', animation: 'Walk', poseId: '' }, { characterId: '' }], card_controls: {},
                                       card_assets: { foreground: '', background: ' counter.png ' }, card_language: '', approve_take: false }),
                   { type: 'apply_series_shot_card', seriesId: '', episodeId: '', shot: 3, card: 'walk-cycle-sheet',
                     cast: [{ characterId: 'gloria', animation: 'walk' }], assets: { background: 'counter.png' }, approve: false })
  const parsed = parseAgentTurn(JSON.stringify({ reply: 'Hecho.', actions: [{ type: 'apply_series_shot_card', shot_number: 3, card_id: 'walk-cycle-sheet' }] }))
  assert.equal(parsed.actions[0]?.type, 'apply_series_shot_card')
})

test('the Wizard posts the same body to the same route as the MCP tool and tells where the take is', async () => {
  const capability = getCapability('apply_series_shot_card')!
  const action = capability.resolve({ type: 'apply_series_shot_card', shot_number: 3, card_id: 'walk-cycle-sheet', card_cast: CAST, approve_take: true })!
  assert.deepEqual(cardBody(action as never, 'show'), { workspace: 'show', card: 'walk-cycle-sheet', cast: CAST, approve: true }, 'the MCP tool sends exactly this')
  const calls: Call[] = []
  const previousFetch = globalThis.fetch
  seriesOpen()
  Object.assign(globalThis, { fetch: async (url: string, init?: { body?: string, headers?: Record<string, string> }) => {
    calls.push({ url, body: JSON.parse(init?.body || '{}'), headers: init?.headers })
    return { ok: true, json: async () => ({ status: 'completed', shotId: 'e1s03', number: 3, card: 'walk-cycle-sheet', scene: 'pu-ep1-e1s03-card-walk-cycle-sheet.scene.json',
                                           take: { attemptId: 'attempt-1', approved: false, reused: false }, warnings: [] }) }
  } })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const outcome = await capability.execute(action as never, { adapters: createDefaultApplicationAdapters(), workspace: 'show' })
    assert.equal(calls.length, 1)
    assert.equal(calls[0].url, '/api/v1/series/pu/episodes/ep1/shots/3/card')
    assert.deepEqual(calls[0].body, { workspace: 'show', card: 'walk-cycle-sheet', cast: CAST, approve: true })
    assert.equal(calls[0].headers?.['X-Hocus-UI-Surface'], 'wizard', 'a take it approves records the Wizard')
    assert.match(outcome.message, /Shot 3 \(e1s03\): the card walk-cycle-sheet is a new take of the shot, waiting for your approval in Series Lab\./)
    assert.match(outcome.message, /pu-ep1-e1s03-card-walk-cycle-sheet\.scene\.json opens in Video 2D/)
    assert.deepEqual(outcome.target, { kind: 'series_episode', id: 'ep1', title: 'e1s03' })
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('a scene still being exported is asked again until the take is attached, and the server\'s refusal reaches the user', async () => {
  seriesOpen()
  const previousFetch = globalThis.fetch
  let posts = 0
  const slept: number[] = []
  Object.assign(globalThis, { fetch: async () => {
    posts += 1
    return { ok: true, json: async () => (posts < 3 ? { status: 'exporting', shotId: 'e1s03', number: 3, card: 'walk-cycle-sheet', scene: 'x.scene.json' }
      : { status: 'completed', shotId: 'e1s03', number: 3, card: 'walk-cycle-sheet', scene: 'x.scene.json', take: { attemptId: 'attempt-1', approved: true, reused: true } }) }
  } })
  try {
    const action = { type: 'apply_series_shot_card', seriesId: '', episodeId: '', shot: 3, card: 'walk-cycle-sheet', approve: true } as const
    const outcome = await executeApplySeriesShotCard(action as never, 'show', async ms => { slept.push(ms) })
    assert.equal(posts, 3)
    assert.equal(slept.length, 2)
    assert.match(outcome.message, /was already the shot's take and I approved it \(one-shot mode\)/)
    Object.assign(globalThis, { fetch: async () => ({ ok: false, json: async () => ({ detail: { code: 'agent_review_off', message: 'Agent approval is off (agent_autonomy is review): a person approves a take in Series Lab.' } }) }) })
    await assert.rejects(executeApplySeriesShotCard(action as never, 'show', async () => {}), /Agent approval is off \(agent_autonomy is review\)/)
    Object.assign(globalThis, { fetch: async () => ({ ok: true, json: async () => ({ status: 'exporting', shotId: 'e1s03', number: 3, card: 'walk-cycle-sheet', scene: 'x.scene.json' }) }) })
    const waiting = await executeApplySeriesShotCard(action as never, 'show', async () => {})
    assert.match(waiting.message, /still being exported; ask me again/)
  } finally {
    globalThis.fetch = previousFetch
  }
  assert.match(cardMessage({ status: 'completed', shotId: 'e1s03', number: 3, card: 'c', scene: 's', approvalNote: 'A person approved another take.', take: { approved: false } }), /A person approved another take\./)
})
