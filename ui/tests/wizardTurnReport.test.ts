import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import i18n from '../src/i18n/index.ts'
import { formatWizardTurnReply, normalizeWizardResult, rejectedWizardAction, withWizardRejections, wizardTurnVisualState } from '../src/features/agent/wizardTurnReport.ts'
import type { AgentActionResult, AgentTurn } from '../src/features/agent/agentActions.ts'

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, { window: dom.window, document: dom.window.document,
  localStorage: dom.window.localStorage, Event: dom.window.Event, CustomEvent: dom.window.CustomEvent })
window.matchMedia = () => ({ matches: false }) as MediaQueryList
const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
const { validateWizardPlan } = await import('../src/features/agent/wizardVisualPolicy.ts')
const t = (key: string, options?: Record<string, unknown>) => String(i18n.t(key, { ns: 'wizard', lng: 'en', ...options }))

test('the planner supplies the interpretation and its question survives navigation receipts', () => {
  const question = '¿Qué mundo te gustaría explorar con esos personajes y para qué público?'
  const proposed = parseAgentTurn(JSON.stringify({ reply: 'He creado invented-series.',
    intent: { kind: 'clarification', execution: 'none', goal: 'Develop an animated episodic project', question },
    actions: [{ type: 'open_tab', tab: 'series_lab' }],
  }))
  const turn = validateWizardPlan(false, proposed)
  const results: AgentActionResult[] = [{ action: turn.actions[0], ok: true, message: 'Opened Series Lab.',
    commandResult: { commandId: 'navigation', status: 'completed', entities: [], artifacts: [], taskIds: [], pipelineIds: [] } }]
  for (const receipts of [[], results]) {
    const reply = formatWizardTurnReply(turn, receipts, t)
    assert.ok(reply.startsWith(question))
    assert.doesNotMatch(reply, /No action was executed|invented-series/)
    assert.equal(wizardTurnVisualState(turn, receipts), 'idle')
  }
})

test('a clarification cannot execute a model-proposed creation while waiting for input', () => {
  const turn = validateWizardPlan(false, parseAgentTurn(JSON.stringify({ reply: 'Created!',
    intent: { kind: 'clarification', execution: 'none', goal: 'Develop a series', question: '¿Qué tono prefieres?' },
    actions: [{ type: 'open_tab', tab: 'series_lab' },
      { type: 'create_series_episode', series_title: 'Invented', episode_premise: 'Invented premise', create_if_missing: true }],
  })))
  assert.deepEqual(turn.actions, [{ type: 'open_tab', tab: 'series_lab' }])
  assert.equal(turn.rejections?.[0].code, 'request_policy')
  assert.match(formatWizardTurnReply(turn, [], t), /¿Qué tono prefieres\?/)
  assert.doesNotMatch(formatWizardTurnReply(turn, [], t), /Created!/)
})

test('a contextual creative delegation keeps the specific plan without inventing a canned example', () => {
  const turn = validateWizardPlan(false, parseAgentTurn(JSON.stringify({ reply: 'Done.',
    intent: { kind: 'action', execution: 'prepare', goal: 'Invent the pilot from the earlier astronomy premise', question: '' },
    actions: [{ type: 'create_series_episode', series_title: 'Órbita de bolsillo',
      series_premise: 'Una familia vive en un observatorio flotante.', episode_title: 'La luna se muda',
      episode_premise: 'La pequeña astrónoma descubre que la luna ha cambiado de vecino.', create_if_missing: true }],
  })))
  assert.equal(turn.actions.length, 1)
  const episode = turn.actions[0]
  assert.equal(episode.type, 'create_series_episode')
  if (episode.type !== 'create_series_episode') throw new Error('Expected episode creation')
  assert.equal(episode.seriesTitle, 'Órbita de bolsillo')
  assert.equal(episode.episodeTitle, 'La luna se muda')
  assert.doesNotMatch(formatWizardTurnReply(turn, [], t), /Done\./)
})

test('a clarification retains its question but cannot gain compute scope from contradictory model fields', () => {
  const turn = validateWizardPlan(false, parseAgentTurn(JSON.stringify({ reply: 'Rendered!',
    intent: { kind: 'clarification', execution: 'run', goal: 'Choose the visual world', question: '¿Cómo imaginas ese mundo?' },
    actions: [{ type: 'prepare_image', prompt: 'invented' }, { type: 'start_generation', confirm: true }],
  })))
  assert.equal(turn.intent?.execution, 'none')
  assert.deepEqual(turn.actions, [])
  assert.match(formatWizardTurnReply(turn, [], t), /¿Cómo imaginas ese mundo\?/)
  assert.doesNotMatch(formatWizardTurnReply(turn, [], t), /Rendered|No action was executed/)
})

test('missing or invalid semantic intent fails closed with an actionable explanation', async () => {
  const { wizardLlmRequestSchema } = await import('../src/features/agent/agentActions.ts')
  assert.ok((wizardLlmRequestSchema().required as string[]).includes('intent'))
  for (const intent of [undefined, { kind: 'completed', goal: 'Made it', question: '' },
    { kind: 'clarification', execution: 'none', goal: 'Plan a series', question: '' }, { kind: 'action', execution: 'run', goal: '', question: '' }]) {
    const turn = validateWizardPlan(false, parseAgentTurn(JSON.stringify({ reply: 'Done!', intent,
      actions: [{ type: 'open_tab', tab: 'series_lab' }] })))
    assert.deepEqual(turn.actions, [])
    assert.ok(turn.rejections?.some(item => item.code === 'invalid_intent'))
    assert.match(formatWizardTurnReply(turn, [], t), /valid interpretation of your intent/)
    assert.doesNotMatch(formatWizardTurnReply(turn, [], t), /Done!/)
  }
})

test('preparation scope rejects proposed computation without recognizing command words', () => {
  const turn = validateWizardPlan(false, parseAgentTurn(JSON.stringify({ reply: 'Launched!',
    intent: { kind: 'action', execution: 'prepare', goal: 'Prepare a still while leaving rendering for later', question: '' },
    actions: [{ type: 'prepare_image', prompt: 'a lighthouse in the fog' }, { type: 'start_generation', confirm: true }],
  })))
  assert.deepEqual(turn.actions.map(action => action.type), ['prepare_image'])
  assert.equal(turn.rejections?.[0].actionType, 'start_generation')
  assert.equal(turn.rejections?.[0].code, 'request_policy')
})

test('rejected create_story exposes the rejection and never displays the invented result', () => {
  const turn = parseAgentTurn(JSON.stringify({ reply: 'I created story-invented successfully.',
    actions: [{ type: 'create_story', title: 'Only a title' }] }))
  assert.equal(turn.actions.length, 0)
  assert.deepEqual(turn.rejections, [{ index: 0, actionType: 'create_story', code: 'invalid_action' }])
  const reply = formatWizardTurnReply(turn, [], t)
  assert.match(reply, /No action was executed/)
  assert.match(reply, /create_story: Unknown action, missing required parameters or invalid values/)
  assert.doesNotMatch(reply, /story-invented|successfully/)
})

test('unknown actions and malformed action lists report bounded local diagnostics', () => {
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Done', actions: [null, { type: 'made_up' }, { type: '<img src=x>' }],
    rejections: [{ code: 'model_says_it_worked' }] }))
  assert.deepEqual(turn.rejections?.map(item => item.actionType), ['unknown', 'made_up', 'unknown'])
  assert.ok(turn.rejections?.every(item => item.code === 'invalid_action'))
  assert.equal(parseAgentTurn(JSON.stringify({ reply: 'Done', actions: {} })).rejections?.[0].code, 'invalid_action_list')
  assert.equal(parseAgentTurn(JSON.stringify({ reply: 'Done', actions: null })).rejections?.[0].code, 'invalid_action_list')
})

test('generation rejected for missing preparation or a second start has an explicit reason', () => {
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Two images created.', actions: [
    { type: 'start_generation', confirm: true }, { type: 'prepare_image', prompt: 'a red boat' },
    { type: 'start_generation', confirm: true }, { type: 'start_generation', confirm: true },
  ] }))
  assert.deepEqual(turn.actions.map(item => item.type), ['prepare_image', 'start_generation'])
  assert.deepEqual(turn.rejections?.map(item => item.code), ['preparation_required', 'duplicate_generation'])
})

test('oversized proposals preserve the execution limit and report truncation', () => {
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Done', actions: Array.from({ length: 100 }, () => ({ type: 'open_tab', tab: 'studio' })) }))
  assert.ok(turn.actions.length > 0 && turn.actions.length < 100)
  assert.equal(turn.rejections?.filter(item => item.code === 'action_limit').length, 1)
})

test('media policy and interpreted conversation retain exclusions instead of silently dropping them', () => {
  const proposal = parseAgentTurn(JSON.stringify({ reply: 'Generated a video.',
    intent: { kind: 'conversation', execution: 'none', goal: 'Explain the video tools', question: '' }, actions: [
    { type: 'create_story', title: 'Missing premise' },
    { type: 'prepare_video', prompt: 'clouds' }, { type: 'start_generation', confirm: true },
  ] }))
  const visual = validateWizardPlan(true, proposal)
  assert.deepEqual(visual.actions, [])
  assert.deepEqual(visual.rejections?.map(item => item.code), ['invalid_action', 'visual_evidence_only', 'visual_evidence_only'])
  const explanation = validateWizardPlan(false, proposal)
  assert.equal(explanation.actions.filter(item => item.type === 'start_generation').length, 0)
  assert.ok(explanation.rejections?.some(item => item.code === 'request_policy'))
  assert.doesNotMatch(formatWizardTurnReply(explanation, [], t), /Generated a video/)
})

test('reconciliation matches full action identity and keeps original indices and diagnostics', () => {
  const before: AgentTurn = { reply: 'Done', actions: [{ type: 'open_tab', tab: 'studio' }, { type: 'open_tab', tab: 'comics' }],
    rejections: [rejectedWizardAction({ type: 'invalid' }, 9)] }
  const actual = withWizardRejections(before, { reply: 'Navigating', actions: before.actions.slice(1) }, 'request_policy')
  assert.deepEqual(actual.rejections?.map(item => item.actionType), ['invalid', 'open_tab'])
  assert.equal(actual.rejections?.[1].index, 0)
  const parsed = parseAgentTurn(JSON.stringify({ reply: '', actions: [{ type: 'unknown' }, { type: 'prepare_image', prompt: 'A' }] }))
  const replaced = withWizardRejections(parsed, { reply: '', actions: [{ type: 'prepare_image', prompt: 'B' }] }, 'request_policy')
  assert.deepEqual(replaced.rejections?.map(item => item.index), [0, 1])
  assert.equal(replaced.rejections?.[1].code, 'request_policy')
  const newlyRejected = withWizardRejections(before, { ...before, rejections: [rejectedWizardAction(null, 4)] }, 'request_policy')
  assert.deepEqual(newlyRejected.rejections?.map(item => item.index), [9, 4])
})

test('a queued receipt cannot be labelled completed by model prose or an ok flag', () => {
  const action = { type: 'start_generation' as const, confirm: true as const }
  const result: AgentActionResult = { action, ok: true, message: 'Submitted job-real-1.', commandResult: {
    commandId: 'command-real-1', status: 'queued', entities: [], artifacts: [], taskIds: ['task-real-1'], pipelineIds: [],
  } }
  const reply = formatWizardTurnReply({ reply: 'The finished movie is invented.mp4.', actions: [action] }, [result], t)
  assert.match(reply, /\*\*Queued\./)
  assert.match(reply, /job-real-1/)
  assert.doesNotMatch(reply, /invented|finished|Completed|Done/)
})

test('failed and awaiting-input results keep real messages without an invented success', () => {
  const action = { type: 'open_tab' as const, tab: 'studio' as const }
  const result: AgentActionResult = { action, ok: false, message: 'Choose a model.', commandResult: {
    commandId: 'cmd', status: 'awaiting_input', entities: [], artifacts: [], taskIds: [], pipelineIds: [],
  } }
  assert.match(formatWizardTurnReply({ reply: '', actions: [action] }, [result], t), /Needs input/)
  const failed = { ...result, commandResult: { ...result.commandResult!, status: 'failed' as const }, message: 'Model unavailable.' }
  assert.match(formatWizardTurnReply({ reply: '', actions: [action] }, [failed], t), /Failed.*Model unavailable/)
})

test('informational conversation is preserved while navigation requires its own result', () => {
  const reply = 'Collections group existing assets.'
  const turn: AgentTurn = { reply, actions: [], intent: { kind: 'conversation', execution: 'none', goal: 'Explain collections', question: '' } }
  assert.equal(formatWizardTurnReply(turn, [], t), reply)
  assert.match(formatWizardTurnReply({ reply, actions: [{ type: 'open_tab', tab: 'workspaces' }] }, [], t), /No action was executed/)
})

test('empty and omitted actions never claim creation in response to an action request', () => {
  for (const payload of [{ actions: [] }, {}]) {
    const turn = parseAgentTurn(JSON.stringify({ reply: 'Created invented-999.', ...payload }))
    const reply = formatWizardTurnReply(turn, [], t)
    assert.match(reply, /No action was executed/)
    assert.doesNotMatch(reply, /invented-999|Created/)
  }
})

test('navigation cannot certify unrelated creation or claim success when it failed', () => {
  const action = { type: 'open_tab' as const, tab: 'studio' as const }
  for (const ok of [true, false]) {
    const result = { action, ok, message: ok ? 'Studio selected.' : 'Studio unavailable.' }
    const reply = formatWizardTurnReply({ reply: 'I opened Studio and created invented-999.', actions: [action] }, [result], t)
    assert.doesNotMatch(reply, /I opened|invented-999/)
    assert.match(reply, ok ? /Reported.*Studio selected/ : /Failed.*Studio unavailable/)
  }
})

test('inconsistent result states are normalized for text, cards and avatar without losing IDs', () => {
  const action = { type: 'start_generation' as const, confirm: true as const }
  const turn = { reply: 'Done', actions: [action] }
  const result: AgentActionResult = { action, ok: false, message: 'Admission failed.',
    commandResult: { commandId: 'cmd-real', status: 'completed', entities: [], artifacts: [], taskIds: ['task-real'], pipelineIds: [] },
    report: { state: 'completed', message: 'Admission failed.', recoverable: true },
  }
  const failed = normalizeWizardResult(result)
  assert.equal(failed.commandResult?.status, 'failed')
  assert.equal(failed.report?.state, 'failed')
  assert.deepEqual(failed.commandResult?.taskIds, ['task-real'])
  assert.equal(wizardTurnVisualState(turn, [failed]), 'error')
  assert.match(formatWizardTurnReply(turn, [failed], t), /Failed/)
  for (const state of ['queued', 'running', 'prepared', 'awaiting_input', 'failed', 'completed'] as const) {
    const actual = normalizeWizardResult({ ...result, ok: true, commandResult: undefined, report: { ...result.report!, state } })
    const expected = state === 'failed' ? 'error' : state === 'completed' ? 'success' : ['queued', 'running'].includes(state) ? 'acting' : 'idle'
    assert.equal(wizardTurnVisualState(turn, [actual]), expected)
  }
})

test('mixed action explanations deliberately use local validation feedback', () => {
  const turn = parseAgentTurn(JSON.stringify({ reply: 'I did not create it because the premise is missing.', actions: [{ type: 'create_story', title: 'Nightwatch' }] }))
  assert.match(formatWizardTurnReply(turn, [], t), /missing required parameters/)
  assert.doesNotMatch(formatWizardTurnReply(turn, [], t), /I did not create it/)
})

test('rejection copy is translated in Spanish', () => {
  const turn = parseAgentTurn(JSON.stringify({ reply: 'Creado.', actions: [{ type: 'create_story', title: 'Sin premisa' }] }))
  const reply = formatWizardTurnReply(turn, [], (key, options) => String(i18n.t(key, { ns: 'wizard', lng: 'es', ...options })))
  assert.match(reply, /No se ha ejecutado ninguna acción/)
  assert.match(reply, /Acciones no ejecutadas/)
  assert.doesNotMatch(reply, /Creado\./)
})

test('an interpreted Flux retry keeps the exact task chosen by the planner', () => {
  const turn = validateWizardPlan(false, {
    reply: 'I finished a comic.', actions: [{ type: 'retry_task', taskId: 'task-generation-67506a65', confirm: true }],
    intent: { kind: 'action', execution: 'run', goal: 'Retry the failed Flux image task', question: '' },
  })
  assert.deepEqual(turn.actions, [{ type: 'retry_task', taskId: 'task-generation-67506a65', confirm: true }])
})

test('an empty interpreted plan cannot manufacture a retry from previous messages', () => {
  const turn = validateWizardPlan(false, { reply: '', actions: [],
    intent: { kind: 'action', execution: 'run', goal: 'Retry the latest failed task', question: '' } })
  assert.deepEqual(turn.actions, [])
})
