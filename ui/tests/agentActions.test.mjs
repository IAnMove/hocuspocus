import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
  Event: dom.window.Event,
  CustomEvent: dom.window.CustomEvent,
})
window.matchMedia = () => ({ matches: false })

test('parses a filled Series Lab episode action without trusting unknown fields', async () => {
  const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
  const turn = parseAgentTurn(JSON.stringify({
    reply: 'Voy a preparar el episodio.',
    actions: [{
      type: 'create_series_episode',
      series_title: 'Seinfeld',
      series_premise: 'Comedia cotidiana sobre cuatro amigos en Nueva York.',
      series_logline: 'Pequeños problemas se convierten en grandes enredos.',
      episode_title: 'El sushi del silencio',
      episode_premise: 'El grupo visita un restaurante donde está prohibido hablar.',
      episode_logline: 'Guardar silencio resulta imposible para todos.',
      genre: 'Comedia', tone: 'Seco y observacional', visual_style: 'Sitcom cinematográfica',
      world_summary: 'Nueva York cotidiana y neurótica.', theme: 'La incomunicación',
      ending: 'El silencio se rompe de la forma menos oportuna.', language: 'Español de España',
      characters: [{
        name: 'Jerry', role: 'Protagonista', personality: 'Observador', desire: 'Evitar el drama',
        flaw: 'Distante', appearance: 'Cómico neoyorquino', voice: 'Irónica', ignored: 'drop me',
      }],
      locations: [{ name: 'Silent Fish', purpose: 'Conflicto', description: 'Restaurante minimalista' }],
      outline_beats: ['Llegada', 'Complicación', 'Remate'],
      target_duration_seconds: 75,
      create_if_missing: true,
      known_universe: true,
      ignored: 'drop me',
    }],
  }))

  assert.equal(turn.actions.length, 1)
  assert.equal(turn.actions[0].type, 'create_series_episode')
  assert.equal(turn.actions[0].seriesTitle, 'Seinfeld')
  assert.equal(turn.actions[0].characters[0].name, 'Jerry')
  assert.equal('ignored' in turn.actions[0], false)
})

test('remembers an internal lab destination requested before its lazy panel mounts', async () => {
  const { listenForAgentSeriesSection, openAgentSeriesSection } = await import('../src/features/agent/agentUiBus.ts')
  openAgentSeriesSection('episode')
  let received = ''
  const unsubscribe = listenForAgentSeriesSection(section => { received = section })
  assert.equal(received, 'episode')
  unsubscribe()
})

test('capability knowledge includes every currently executable action family', async () => {
  const { AGENT_CAPABILITIES, buildAgentCapabilityGuide } = await import('../src/features/agent/agentCapabilities.ts')
  assert.deepEqual(
    AGENT_CAPABILITIES.map(item => item.type),
    ['open_tab', 'prepare_video', 'open_story_section', 'open_series_section', 'start_generation', 'create_story', 'create_series_episode', 'inspect_queue', 'cancel_task', 'resume_task'],
  )
  assert.match(buildAgentCapabilityGuide(), /create_series_episode/)
})

test('drops cancel_task unless confirm is true and repairs an explicit cancel request', async () => {
  const { parseAgentTurn, reconcileAgentTurnWithRequest } = await import('../src/features/agent/agentActions.ts')
  const unsigned = parseAgentTurn(JSON.stringify({
    reply: 'Cancelo.',
    actions: [{ type: 'cancel_task', task_id: 'task-1', confirm: false }],
  }))
  assert.equal(unsigned.actions.length, 0)
  const signed = parseAgentTurn(JSON.stringify({
    reply: 'Cancelo.',
    actions: [{ type: 'cancel_task', task_id: 'task-1', confirm: true }],
  }))
  assert.equal(signed.actions[0].type, 'cancel_task')
  assert.equal(signed.actions[0].taskId, 'task-1')
  const repaired = reconcileAgentTurnWithRequest('cancela el trabajo activo', { reply: 'Vale.', actions: [] })
  assert.equal(repaired.actions[0].type, 'cancel_task')
  assert.equal(repaired.actions[0].confirm, true)
})
