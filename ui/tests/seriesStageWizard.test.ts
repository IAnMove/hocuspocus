import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { HOCUSPOCUS_AGENT_RESPONSE_SCHEMA, parseAgentTurn } from '../src/features/agent/agentActions.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { projectWizardContextCapabilities } from '../src/features/agent/wizardCapabilityAvailability.ts'
import { stageCheckBody, stageCheckMessage, stageSetBody, stageSetMessage } from '../src/features/agent/seriesStageCapabilities.ts'
import { useSeriesStore } from '../src/features/series/store.ts'

type Call = { url: string, body: Record<string, unknown>, headers?: Record<string, string> }

function seriesOpen(locations = [{ id: 'office', name: 'Despacho' }, { id: 'hangar', name: 'Hangar' }]) {
  useSeriesStore.setState({ workspace: 'show', activeSeriesId: 'ls', activeEpisodeId: '', saveNow: async () => null, reload: async () => undefined,
    library: { seriesById: { ls: { id: 'ls', locations } } } } as never)
}

const SET = { type: 'set_series_location_stage', series_id: '', location_id: 'office', horizon: 0.22, ref_base_y: 0.72, ref_height_pct: 0.62, ref_height_m: 0 }

test('the plate stage is two registered Wizard actions with the MCP tools\' fields', () => {
  for (const name of ['set_series_location_stage', 'check_series_location_stage']) {
    assert.equal(AGENT_ACTION_TYPES.includes(name as never), true, name)
    assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, new RegExp(name))
  }
  const properties = (HOCUSPOCUS_AGENT_RESPONSE_SCHEMA as { properties: { actions: { items: { properties: Record<string, unknown> } } } })
    .properties.actions.items.properties
  for (const key of ['location_id', 'horizon', 'ref_base_y', 'ref_height_pct', 'ref_height_m', 'floor_top', 'clear', 'grid_step']) assert.ok(properties[key], key)
  assert.equal(getCapability('set_series_location_stage')!.risk, 'edit')
  assert.equal(getCapability('check_series_location_stage')!.risk, 'read')
  const parsed = parseAgentTurn(JSON.stringify({ reply: 'Hecho.', actions: [SET] }))
  assert.equal(parsed.actions[0]?.type, 'set_series_location_stage')
})

test('the model\'s empty fields name nothing and a stage needs the horizon and the reference', () => {
  const set = getCapability('set_series_location_stage')!
  assert.deepEqual(set.resolve({ ...SET, clear: false, floor_top: 0 }), { type: 'set_series_location_stage', seriesId: '', locationId: 'office', horizon: 0.22,
    ref: { baseY: 0.72, heightPct: 0.62 }, clear: false })
  assert.deepEqual(set.resolve({ ...SET, ref_height_m: 2.1, floor_top: 0.6 }), { type: 'set_series_location_stage', seriesId: '', locationId: 'office', horizon: 0.22,
    ref: { baseY: 0.72, heightPct: 0.62, heightM: 2.1 }, floorTop: 0.6, clear: false })
  assert.equal(set.resolve({ ...SET, horizon: 0 }), null, 'no horizon')
  assert.equal(set.resolve({ ...SET, ref_height_pct: 0 }), null, 'no reference')
  assert.deepEqual(set.resolve({ type: 'set_series_location_stage', location_id: 'office', horizon: 0, clear: true }), { type: 'set_series_location_stage', seriesId: '', locationId: 'office', clear: true })
  const resolved = set.resolve({ ...SET, horizon: 0.8 })!
  assert.equal(set.validate(resolved as never).length, 1, 'the reference foot must be below the horizon')
  const check = getCapability('check_series_location_stage')!
  assert.deepEqual(check.resolve({ type: 'check_series_location_stage', series_id: '', location_id: '', horizon: 0, ref_base_y: 0, ref_height_pct: 0, grid_step: 0 }),
    { type: 'check_series_location_stage', seriesId: '', locationId: '' })
  assert.deepEqual(check.resolve({ type: 'check_series_location_stage', location_id: 'office', grid_step: 0.05, horizon: 0.22, ref_base_y: 0.72, ref_height_pct: 0.62 }),
    { type: 'check_series_location_stage', seriesId: '', locationId: 'office', horizon: 0.22, ref: { baseY: 0.72, heightPct: 0.62 }, step: 0.05 })
})

test('the Wizard posts the same bodies to the same routes as the MCP tools and tells the camera height', async () => {
  const set = getCapability('set_series_location_stage')!
  const action = set.resolve(SET)!
  assert.deepEqual(stageSetBody(action as never, 'show'), { workspace: 'show', horizon: 0.22, ref: { baseY: 0.72, heightPct: 0.62 } }, 'the MCP tool sends exactly this')
  assert.deepEqual(stageSetBody({ ...action, clear: true } as never, 'show'), { workspace: 'show', clear: true })
  const calls: Call[] = []
  const previousFetch = globalThis.fetch
  seriesOpen()
  Object.assign(globalThis, { fetch: async (url: string, init?: { body?: string, headers?: Record<string, string> }) => {
    calls.push({ url, body: JSON.parse(init?.body || '{}'), headers: init?.headers })
    return { ok: true, json: async () => url.endsWith('/check')
      ? { locationId: 'office', plate: { file: 'day.png' }, grid: { file: 'stage-check-office-ab.png', url: '/api/v1/file/stage-check-office-ab.png?workspace=show', step: 0.1 },
          suggestion: { suggestion: { horizon: 0.31, confidence: 'medium' } }, eyeHeightM: 1.61 }
      : { locationId: 'office', stage: { horizon: 0.22 }, affectedShots: ['s1', 's2'], eyeHeightM: 0.7, warning: 'this stage puts the camera 0.7 m high' } }
  } })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const context = { adapters: createDefaultApplicationAdapters(), workspace: 'show' }
    const saved = await set.execute(action as never, context)
    assert.equal(calls[0].url, '/api/v1/series/ls/locations/office/stage')
    assert.deepEqual(calls[0].body, { workspace: 'show', horizon: 0.22, ref: { baseY: 0.72, heightPct: 0.62 } })
    assert.equal(calls[0].headers?.['X-Hocus-UI-Surface'], 'wizard')
    assert.match(saved.message, /The stage of Despacho is saved: .* 2 shots render again .* camera 0\.7 m high\. this stage puts the camera 0\.7 m high/)
    assert.deepEqual(saved.target, { kind: 'series', id: 'ls', title: 'Despacho' })
    const check = getCapability('check_series_location_stage')!
    const looked = await check.execute(check.resolve({ type: 'check_series_location_stage', location_id: 'office', grid_step: 0.05 })! as never, context)
    assert.equal(calls[1].url, '/api/v1/series/ls/locations/office/stage/check')
    assert.deepEqual(calls[1].body, { workspace: 'show', step: 0.05 })
    assert.match(looked.message, /stage-check-office-ab\.png \(open \/api\/v1\/file\/stage-check-office-ab\.png\?workspace=show\)/)
    assert.match(looked.message, /only a guess: 0\.31 \(confidence medium\).*I cannot see the image/)
    assert.equal(stageCheckBody({ type: 'check_series_location_stage', seriesId: '', locationId: '' }, 'show').step, undefined)
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('the open series\' only location is the default, a named one wins, and the server\'s refusal reaches the user', async () => {
  const { executeSetSeriesLocationStage, stageTarget } = await import('../src/features/agent/seriesStageCapabilities.ts')
  seriesOpen([{ id: 'office', name: 'Despacho' }])
  assert.deepEqual(await stageTarget('', '', undefined, false), { workspace: 'show', seriesId: 'ls', locationId: 'office', location: 'Despacho' })
  seriesOpen()
  await assert.rejects(stageTarget('', '', undefined, false), /Name the location/)
  assert.equal((await stageTarget('', 'hangar', 'other', false)).location, 'Hangar')
  const previousFetch = globalThis.fetch
  Object.assign(globalThis, { fetch: async () => ({ ok: false, json: async () => ({ detail: { code: 'invalid_stage', message: 'stage.ref.baseY (0.2) must be below the horizon (0.5)' } }) }) })
  try {
    await assert.rejects(executeSetSeriesLocationStage({ type: 'set_series_location_stage', seriesId: '', locationId: 'office', horizon: 0.5, ref: { baseY: 0.2, heightPct: 0.1 }, clear: false }, 'show'),
      /must be below the horizon/)
  } finally {
    globalThis.fetch = previousFetch
  }
  assert.match(stageSetMessage({ stage: null }, 'Despacho'), /stage of Despacho is removed/)
  assert.doesNotMatch(stageCheckMessage({ grid: { file: 'g.png', url: '/u' } }, 'Despacho'), /undefined/)
})

test('both actions need an open series', () => {
  const context = (series_id: string) => ({ location: { tab: 'series_lab' }, labs: { story: { project_id: '' }, series: { series_id, episode_id: '', shots: 0, approved: 0 } } })
  const blocked = projectWizardContextCapabilities(context('') as never)
  assert.ok(blocked.blocked.some(entry => entry.name === 'set_series_location_stage'))
  assert.ok(blocked.blocked.some(entry => entry.name === 'check_series_location_stage'))
  const open = projectWizardContextCapabilities(context('ls') as never)
  assert.ok(open.available.includes('set_series_location_stage') && open.available.includes('check_series_location_stage'), 'no episode needed')
})
