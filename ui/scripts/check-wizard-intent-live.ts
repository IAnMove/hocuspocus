import assert from 'node:assert/strict'
import { buildAgentTurnPrompt, HOCUSPOCUS_AGENT_SYSTEM_PROMPT, type AgentConversationEntry } from '../src/features/agent/agentKnowledge'
import { parseAgentTurn, wizardLlmRequestSchema, type AgentAppSnapshot } from '../src/features/agent/agentActions'
import { validateWizardPlan } from '../src/features/agent/wizardVisualPolicy'

// Calls the configured LLM only. No planned action or media job is executed.
const baseUrl = String(process.env.HOCUSPOCUS_BASE_URL || '').replace(/\/$/, '')
if (!/^https?:\/\/(?:127\.0\.0\.1|localhost|\[::1\])(?::\d+)?$/i.test(baseUrl)) {
  throw new Error('Set HOCUSPOCUS_BASE_URL to the exact loopback HocusPocus URL.')
}
const app = { interface_language: 'es', current: { media_filter: 'series' }, available_video_models: [],
  context: { location: { tab: 'series_lab' }, labs: { series: { series_id: '', episode_id: '' } } },
} as unknown as AgentAppSnapshot
const history: AgentConversationEntry[] = [
  { role: 'user', text: 'quiero hacer una serie de animacion' },
  { role: 'assistant', text: '¿Cuál es la premisa, el público, el estilo visual y la duración objetivo del primer episodio de tu serie de animación?' },
]
const cases: Array<{ id: string; history: AgentConversationEntry[]; request: string; kind: string }> = [
  { id: 'creative-direction-after-question', history,
    request: 'quiero que nos inspiremos en south park en cuanto al estilo, pero que sea sobre los investigadores de inteligencia artificial americanos, para el lore y demas podemos inspirarnos en la serie "silicon valley"', kind: 'action' },
  { id: 'indirect-direction-after-question', history,
    request: 'Los protagonistas serían unos científicos que compiten por inventar la próxima gran IA en California. Los imagino como recortes de papel, con humor ácido sobre sus egos y los inversores. Todavía no se me ha ocurrido cómo llamarla.', kind: 'action' },
  { id: 'discussion-before-saving', history,
    request: 'Una sátira de investigadores de IA, dibujada con recortes de papel. Antes de guardar nada quiero que conversemos sobre una posible premisa; todavía no crees el proyecto.', kind: 'conversation' },
  { id: 'no-creative-direction', history: [], request: 'quiero hacer una serie de animacion', kind: 'clarification' },
]
for (const item of cases) {
  const response = await fetch(`${baseUrl}/api/v1/llm/generate`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: AbortSignal.timeout(60_000),
    body: JSON.stringify({ system_prompt: HOCUSPOCUS_AGENT_SYSTEM_PROMPT,
      prompt: buildAgentTurnPrompt('intent_contract_check', [...item.history, { role: 'user', text: item.request }], [], app),
      max_new_tokens: 3_200, temperature: .1, json_schema: wizardLlmRequestSchema() }),
  })
  assert.equal(response.status, 200, item.id)
  const raw = String((await response.json() as { text?: string }).text || '')
  const turn = validateWizardPlan(false, parseAgentTurn(raw))
  assert.equal(turn.intent?.kind, item.kind, `${item.id}: ${raw}`)
  assert.equal(turn.rejections?.length || 0, 0, `${item.id}: ${JSON.stringify(turn.rejections)}`)
  if (item.kind === 'action') {
    assert.equal(turn.intent?.execution, 'prepare', item.id)
    const episode = turn.actions.find(action => action.type === 'create_series_episode')
    assert.ok(episode, `${item.id}: missing first draft`)
    assert.equal(episode.createIfMissing, true, item.id)
    assert.equal(episode.knownUniverse, false, `${item.id}: style references are not the existing universe`)
    for (const field of ['seriesTitle', 'seriesPremise', 'worldSummary', 'visualStyle', 'episodeTitle', 'episodePremise'] as const) {
      assert.ok(episode[field].trim(), `${item.id}: empty ${field}`)
    }
    assert.ok(episode.characters.length >= 3 && episode.locations.length >= 1 && episode.outlineBeats.length >= 3, item.id)
    assert.ok(turn.actions.every(action => action.type === 'create_series_episode'
      || action.type === 'open_tab' || action.type === 'open_series_section'), `${item.id}: unexpected extra work`)
    console.log(JSON.stringify({ id: item.id, series: episode.seriesTitle, premise: episode.seriesPremise,
      episode: episode.episodeTitle, episodePremise: episode.episodePremise, executed: false }))
  } else {
    assert.equal(turn.intent?.execution, 'none', item.id)
    if (item.kind === 'conversation') {
      assert.deepEqual(turn.actions, [], item.id)
      assert.ok(turn.reply.length > 40, item.id)
    } else assert.ok(turn.intent?.question, item.id)
    console.log(JSON.stringify({ id: item.id, kind: turn.intent?.kind, executed: false }))
  }
}
console.log('4 live intent checks passed; no series, episode or media was created.')
