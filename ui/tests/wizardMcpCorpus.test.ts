import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import i18n from '../src/i18n/index.ts'
import { formatWizardTurnReply } from '../src/features/agent/wizardTurnReport.ts'
import { orderCompoundActions } from '../src/features/agent/agentContract.ts'

const corpusPath = join(dirname(fileURLToPath(import.meta.url)), '../../tests/fixtures/wizard_mcp_corpus.json')
const corpus = JSON.parse(readFileSync(corpusPath, 'utf8')) as WizardMcpCorpus

const dom = new JSDOM('<!doctype html><html><body /></html>', { url: 'http://localhost/' })
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
  Event: dom.window.Event,
  CustomEvent: dom.window.CustomEvent,
})
window.matchMedia = () => ({ matches: false }) as MediaQueryList

const { parseAgentTurn } = await import('../src/features/agent/agentActions.ts')
const { validateWizardPlan } = await import('../src/features/agent/wizardVisualPolicy.ts')

const tEn = (key: string, options?: Record<string, unknown>) => String(i18n.t(key, { ns: 'wizard', lng: 'en', ...options }))
const tEs = (key: string, options?: Record<string, unknown>) => String(i18n.t(key, { ns: 'wizard', lng: 'es', ...options }))

interface CorpusExpect {
  action_types?: string[]
  forbidden_action_types?: string[]
  ordered_predecessors?: string[]
  rejection_codes?: string[]
  creates_task?: boolean
  promise_success?: boolean
  unpublished?: boolean
  parser_drops_unprepared_start?: boolean
  reply_must_not_match?: string[]
}

interface CorpusCase {
  id: string
  lang: 'en' | 'es'
  kind: string
  surface: 'wizard' | 'mcp' | 'both'
  request?: string
  proposal?: { reply?: string; actions: unknown[] }
  expect: CorpusExpect
}

interface WizardMcpCorpus {
  expect_actions_not_prose: boolean
  published_operations: string[]
  unpublished_operations: string[]
  cases: CorpusCase[]
}

function translate(lang: 'en' | 'es') {
  return lang === 'es' ? tEs : tEn
}

test('shared corpus fixture is bilingual and action-oriented', () => {
  assert.equal(corpus.expect_actions_not_prose, true)
  assert.ok(corpus.published_operations.includes('generation.image'))
  assert.ok(corpus.published_operations.includes('generation.image'))
  assert.ok(corpus.unpublished_operations.includes('generation.model3d'))
  const kinds = new Set(corpus.cases.map(item => item.kind))
  for (const kind of ['intent', 'negation', 'ambiguous', 'workspace_change', 'retry', 'compound', 'unpublished']) {
    assert.ok(kinds.has(kind), kind)
  }
  assert.ok(corpus.cases.some(item => item.lang === 'en'))
  assert.ok(corpus.cases.some(item => item.lang === 'es'))
})

test('wizard corpus cases keep receipts, not invented LLM success', async () => {
  for (const item of corpus.cases) {
    if (item.surface === 'mcp' || !item.proposal) continue
    const parsed = parseAgentTurn(JSON.stringify(item.proposal))
    const turn = validateWizardPlan(false, parsed)
    const types = turn.actions.map(action => action.type)
    if (item.expect.action_types) {
      assert.deepEqual(types, item.expect.action_types, item.id)
    }
    for (const forbidden of item.expect.forbidden_action_types || []) {
      assert.ok(!types.includes(forbidden as typeof types[number]), `${item.id} still has ${forbidden}`)
    }
    if (item.expect.rejection_codes) {
      const codes = (parsed.rejections || []).map(rejection => rejection.code)
      for (const code of item.expect.rejection_codes) {
        assert.ok(codes.includes(code as typeof codes[number]), `${item.id} missing rejection ${code}`)
      }
    }
    if (item.expect.creates_task === false) {
      assert.ok(!types.includes('start_generation'), item.id)
    }
    const reply = formatWizardTurnReply(turn, [], translate(item.lang))
    const actionBearing = Boolean(turn.actions.length || turn.rejections?.length)
    if (actionBearing && item.expect.promise_success === false) {
      assert.doesNotMatch(reply, /Completed|Completado|successfully|con éxito/i)
    }
    if (actionBearing) {
      for (const fragment of item.expect.reply_must_not_match || []) {
        assert.doesNotMatch(reply, new RegExp(fragment.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')))
      }
    }
    if (item.expect.creates_task === false && types.length === 0 && actionBearing && turn.intent?.kind !== 'clarification') {
      assert.match(reply, item.lang === 'es'
        ? /No se ha ejecutado ninguna acción/
        : /No action was executed/)
    }
  }
})

test('compound story song predecessors are explicit and ordered', () => {
  const item = corpus.cases.find(entry => entry.id === 'es-compound-story-song')
  assert.ok(item?.proposal)
  const parsed = parseAgentTurn(JSON.stringify(item.proposal))
  const ordered = orderCompoundActions(parsed.actions).map(action => action.type)
  assert.deepEqual(ordered, item.expect.ordered_predecessors)
})

test('unpublished wizard tool cannot display a finished artifact', () => {
  const item = corpus.cases.find(entry => entry.id === 'es-unpublished-unknown-action')
  assert.ok(item?.proposal)
  const turn = parseAgentTurn(JSON.stringify(item.proposal))
  assert.equal(turn.actions.length, 0)
  assert.equal(turn.rejections?.[0].code, 'invalid_action')
  const reply = formatWizardTurnReply(turn, [], tEs)
  assert.match(reply, /No se ha ejecutado ninguna acción/)
  assert.match(reply, /generation_video/)
  assert.doesNotMatch(reply, /invented\.mp4/)
})

test('a dropped action proposal cannot become an informational success claim', async () => {
  const item = corpus.cases.find(entry => entry.id === 'en-how-to-image')
  assert.ok(item?.proposal && item.request)
  const turn = validateWizardPlan(false, parseAgentTurn(JSON.stringify(item.proposal)))
  assert.deepEqual(turn.actions, [])
  const reply = formatWizardTurnReply(turn, [], tEn)
  assert.match(reply, /No action was executed/)
  assert.doesNotMatch(reply, /invented\.png/)
})

test('queued execution reports keep real IDs without completing', async () => {
  const { executionReport } = await import('../src/features/agent/agentContract.ts')
  const action = { type: 'start_generation' as const, confirm: true as const }
  const result = {
    action,
    ok: true,
    message: 'Submitted job-corpus-1 (task-corpus-1).',
    commandResult: {
      commandId: 'corpus-timeout',
      status: 'queued' as const,
      entities: [],
      artifacts: [],
      taskIds: ['task-corpus-1'],
      pipelineIds: [],
    },
    report: executionReport({
      state: 'queued',
      message: 'Submitted job-corpus-1 (task-corpus-1).',
      taskId: 'task-corpus-1',
      recoverable: true,
    }),
  }
  const reply = formatWizardTurnReply({ reply: 'The finished movie is invented.mp4.', actions: [action] }, [result], tEn)
  assert.match(reply, /\*\*Queued\./)
  assert.match(reply, /job-corpus-1/)
  assert.match(reply, /task-corpus-1/)
  assert.doesNotMatch(reply, /invented\.mp4|Completed/)
})
