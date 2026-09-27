import type { AgentActionResult, AgentTurn } from './agentActions'
import { stableSerialize } from './agentContract'
import type { AgentVisualState } from './AgentAvatar'

export type WizardRejectionCode = 'invalid_action' | 'invalid_action_list' | 'action_limit'
  | 'preparation_required' | 'duplicate_generation' | 'request_policy' | 'visual_evidence_only' | 'invalid_intent'

export interface WizardActionRejection {
  index: number
  actionType: string
  code: WizardRejectionCode
}

/** Retain bounded diagnostics, never arbitrary model payloads or model-supplied reasons. */
export function rejectedWizardAction(value: unknown, index: number,
  code: WizardRejectionCode = 'invalid_action'): WizardActionRejection {
  const type = value && typeof value === 'object' && 'type' in value ? value.type : ''
  return { index, actionType: typeof type === 'string' && /^[a-zA-Z][a-zA-Z0-9_]{0,79}$/.test(type) ? type : 'unknown', code }
}

/** Reconciliation may replace a proposal; keep the exclusions when it builds a new turn. */
export function withWizardRejections(before: AgentTurn, after: AgentTurn,
  code: 'request_policy' | 'visual_evidence_only'): AgentTurn {
  const counts = new Map<string, number>()
  for (const action of after.actions) {
    const key = stableSerialize(action)
    counts.set(key, (counts.get(key) || 0) + 1)
  }
  const rejections = [...(before.rejections || [])]
  for (const rejection of after.rejections || []) {
    if (!rejections.some(item => stableSerialize(item) === stableSerialize(rejection))) rejections.push(rejection)
  }
  before.actions.forEach((action, index) => {
    const key = stableSerialize(action)
    const remaining = counts.get(key) || 0
    if (remaining) counts.set(key, remaining - 1)
    else rejections.push(rejectedWizardAction(action, before.proposalIndices?.[index] ?? index, code))
  })
  return { ...after, ...(rejections.length ? { rejections } : {}) }
}

type Translate = (key: string, options?: Record<string, unknown>) => string

export function wizardResultState(result: AgentActionResult) {
  const states = [result.commandResult?.status, result.report?.state]
  if (states.includes('failed')) return 'failed'
  if (states.includes('awaiting_input')) return 'awaiting_input'
  if (!result.ok) return 'failed'
  for (const state of ['partial', 'queued', 'running', 'prepared', 'completed'] as const) {
    if (states.includes(state)) return state
  }
  return 'reported'
}

/** Use one defensive state for text, cards and the avatar; retain real receipt IDs. */
export function normalizeWizardResult(result: AgentActionResult): AgentActionResult {
  const state = wizardResultState(result)
  if (state === 'reported') return result
  return {
    ...result,
    ok: result.ok && !['failed', 'awaiting_input'].includes(state),
    ...(result.commandResult && state !== 'running' && state !== 'prepared'
      ? { commandResult: { ...result.commandResult, status: state } } : {}),
    ...(result.report ? { report: { ...result.report, state } } : {}),
  }
}

export function wizardTurnVisualState(turn: AgentTurn, results: AgentActionResult[]): AgentVisualState {
  const states = results.map(wizardResultState)
  if (turn.rejections?.length || states.some(state => ['failed', 'partial'].includes(state))) return 'error'
  if (states.some(state => state === 'queued' || state === 'running')) return 'acting'
  if (turn.intent?.kind === 'clarification') return 'idle'
  return states.length && states.every(state => state === 'completed') ? 'success' : 'idle'
}

/** Free-form model prose cannot certify the result of an action-bearing turn. */
export function formatWizardTurnReply(turn: AgentTurn, results: AgentActionResult[], t: Translate): string {
  const hasActions = Boolean(turn.actions.length || results.length || turn.rejections?.length)
  const explanation = !hasActions && turn.intent?.kind === 'conversation'
  const question = turn.intent?.kind === 'clarification' ? turn.intent.question : ''
  const paragraphs: string[] = []
  if (question) paragraphs.push(question)
  if (explanation && turn.reply) paragraphs.push(turn.reply)
  if (results.length) {
    const lines = results.map(result => {
      const label = t(`executionState.${wizardResultState(result)}`)
      return `- **${label}.** ${result.message}`
    })
    paragraphs.push(`### ${t('actionReport')}\n${lines.join('\n')}`)
  } else if (!explanation && !question) paragraphs.push(t('noActionReceipt'))
  if (turn.rejections?.length) {
    const lines = turn.rejections.map(rejection => `- ${t('rejectedAction', {
      action: rejection.actionType,
      reason: t(`rejectionReason.${rejection.code}`),
    })}`)
    paragraphs.push(`### ${t('rejectedActions')}\n${lines.join('\n')}`)
  }
  return paragraphs.join('\n\n') || t('emptyReply')
}
