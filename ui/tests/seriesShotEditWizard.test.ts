import assert from 'node:assert/strict'
import test from 'node:test'
import { AGENT_ACTION_TYPES } from '../src/features/agent/agentActionTypes.ts'
import { HOCUSPOCUS_AGENT_RESPONSE_SCHEMA, parseAgentTurn } from '../src/features/agent/agentActions.ts'
import { getCapability } from '../src/features/agent/capabilityRegistry.ts'
import { HOCUSPOCUS_AGENT_SYSTEM_PROMPT } from '../src/features/agent/agentKnowledge.ts'
import { shotEditMessage, shotRef } from '../src/features/agent/seriesShotEditCapabilities.ts'
import { useSeriesStore } from '../src/features/series/store.ts'

type Call = { url: string, body: Record<string, unknown> }

function fakeServer(reply: Record<string, unknown>, calls: Call[]) {
  return async (url: string, init?: { body?: string }) => {
    if (url.includes('/shots/edit')) {
      calls.push({ url, body: JSON.parse(init?.body || '{}') })
      return { ok: true, json: async () => reply }
    }
    return { ok: true, json: async () => ({ seriesById: {}, revision: 1 }) }
  }
}

test('"edita el quinto plano y ponle un sombrero" becomes one shot edit with the user\'s words', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('edit_series_shot'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /edit_series_shot/)
  const properties = (HOCUSPOCUS_AGENT_RESPONSE_SCHEMA as { properties: { actions: { items: { properties: Record<string, unknown> } } } })
    .properties.actions.items.properties
  for (const key of ['shot_number', 'shot_id', 'changes', 'append']) assert.ok(properties[key], key)
  const capability = getCapability('edit_series_shot')
  assert.ok(capability)
  // The LLM fills unused fields with 0, "" and {}: those name nothing.
  assert.equal(capability.resolve({ type: 'edit_series_shot', shot_number: 0, shot_id: '', instruction: 'ponle un sombrero' }), null)
  assert.equal(capability.resolve({ type: 'edit_series_shot', shot_number: 5, instruction: '', changes: {}, append: {} }), null)
  assert.equal(shotRef({ shot_number: 0, shot_id: 'e1s04' }), 'e1s04')
  const action = capability.resolve({ type: 'edit_series_shot', series_id: '', episode_id: '', shot_number: 5, shot_id: '',
                                      instruction: 'ponle un sombrero a Kevin', changes: {}, append: {} })
  assert.deepEqual(action, { type: 'edit_series_shot', seriesId: '', episodeId: '', shot: 5, instruction: 'ponle un sombrero a Kevin' })
  const parsed = parseAgentTurn(JSON.stringify({ reply: 'Hecho.', actions: [{ type: 'edit_series_shot', shot_number: 5, instruction: 'ponle un sombrero' }] }))
  assert.equal(parsed.actions[0]?.type, 'edit_series_shot')

  const calls: Call[] = []
  const previousFetch = globalThis.fetch
  useSeriesStore.setState({ workspace: 'show', activeSeriesId: 'pu', activeEpisodeId: 'ep1', saveNow: async () => null, reload: async () => undefined })
  Object.assign(globalThis, { fetch: fakeServer({
    shotId: 'e1s04', number: 5, changed: ['props'], approvalReset: true, missingLines: {},
    instruction: { summary: 'Le pongo el sombrero a Kevin' },
  }, calls) })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const outcome = await capability.execute(action!, { adapters: createDefaultApplicationAdapters(), workspace: 'show' })
    assert.equal(calls[0].url, '/api/v1/series/pu/episodes/ep1/shots/edit')
    assert.deepEqual(calls[0].body, { workspace: 'show', shot: 5, instruction: 'ponle un sombrero a Kevin' })
    assert.match(outcome.message, /Plano 5 \(e1s04\) editado: props\. Le pongo el sombrero a Kevin\./)
    assert.match(outcome.message, /aprobación se quitó/)
  } finally {
    globalThis.fetch = previousFetch
  }
})

test('an exact edit is sent as changes and rendering again is a separate confirmed action', async () => {
  const edit = getCapability('edit_series_shot')!
  const exact = edit.resolve({ type: 'edit_series_shot', shot_id: 'e1s02', instruction: 'cámara que se acerque', changes: { camera: 'push' } })
  assert.deepEqual(exact, { type: 'edit_series_shot', seriesId: '', episodeId: '', shot: 'e1s02', instruction: 'cámara que se acerque',
                            changes: { camera: 'push' } })
  const rerender = getCapability('rerender_series_shot')!
  assert.equal(rerender.risk, 'compute')
  assert.equal(rerender.resolve({ type: 'rerender_series_shot', shot_number: 5 }), null, 'needs confirm')
  const action = rerender.resolve({ type: 'rerender_series_shot', shot_number: 5, confirm: true, produce: false })
  const calls: Call[] = []
  const previousFetch = globalThis.fetch
  useSeriesStore.setState({ workspace: 'show', activeSeriesId: 'pu', activeEpisodeId: 'ep1', saveNow: async () => null, reload: async () => undefined })
  Object.assign(globalThis, { fetch: fakeServer({ shotId: 'e1s04', number: 5, changed: [], render: { jobId: 'native-1' } }, calls) })
  try {
    const { createDefaultApplicationAdapters } = await import('../src/features/agent/applicationAdapters.ts')
    const outcome = await rerender.execute(action!, { adapters: createDefaultApplicationAdapters(), workspace: 'show' })
    assert.deepEqual(calls[0].body, { workspace: 'show', shot: 5, render: true, approve: true })
    assert.equal(outcome.jobId, 'native-1')
    assert.match(outcome.message, /renderizando de nuevo/)
  } finally {
    globalThis.fetch = previousFetch
  }
  assert.match(shotEditMessage({ shotId: 'e1s09', number: 10, note: 'laid at the cut' }), /Plano 10 \(e1s09\): laid at the cut/)
})

test('"vuelve a grabar la segunda línea del plano 12" records that line through the shot voice route and waits for it', async () => {
  assert.equal(AGENT_ACTION_TYPES.includes('regenerate_series_line_voice'), true)
  assert.match(HOCUSPOCUS_AGENT_SYSTEM_PROMPT, /regenerate_series_line_voice/)
  const capability = getCapability('regenerate_series_line_voice')!
  assert.equal(capability.risk, 'compute')
  assert.equal(capability.resolve({ type: 'regenerate_series_line_voice', shot_number: 12, line_number: 2 }), null, 'needs confirm')
  assert.equal(capability.resolve({ type: 'regenerate_series_line_voice', shot_number: 12, line_number: 0, confirm: true }), null, 'needs a line')
  const action = capability.resolve({ type: 'regenerate_series_line_voice', shot_number: 12, line_number: 2, retake: true, confirm: true })
  assert.deepEqual(action, { type: 'regenerate_series_line_voice', seriesId: '', episodeId: '', shot: 12, line: 2, retake: true, confirm: true })
  const calls: Call[] = []
  const previousFetch = globalThis.fetch
  useSeriesStore.setState({ workspace: 'show', activeSeriesId: 'pu', activeEpisodeId: 'ep1', saveNow: async () => null, reload: async () => undefined })
  let polls = 0
  Object.assign(globalThis, { fetch: async (url: string, init?: { body?: string }) => {
    calls.push({ url, body: JSON.parse(init?.body || '{}') })
    if (url.endsWith('/voices')) return { ok: true, json: async () => ({ jobId: 'voice-1', status: 'queued', beatId: 'e1s11_b1' }) }
    polls += 1
    return { ok: true, json: async () => ({ jobId: 'voice-1', status: polls > 1 ? 'completed' : 'running', result: { filename: 'ln-ep1-e1s11_b1-abc.wav' } }) }
  } })
  try {
    const { executeSeriesLineVoice } = await import('../src/features/agent/seriesShotEditCapabilities.ts')
    const outcome = await executeSeriesLineVoice(action as never, 'show', async () => {})
    assert.equal(calls[0].url, '/api/v1/series/pu/episodes/ep1/shots/12/voices')
    assert.deepEqual(calls[0].body, { workspace: 'show', line: 2, retake: true })
    assert.equal(calls[1].url, '/api/v1/series/voice-jobs/voice-1?workspace=show')
    assert.match(outcome.message, /Línea 2 del plano 12: otra toma grabada \(ln-ep1-e1s11_b1-abc\.wav\)\. La toma del plano aún no la tiene/)
    assert.equal(outcome.jobId, 'voice-1')
  } finally {
    globalThis.fetch = previousFetch
  }
})
