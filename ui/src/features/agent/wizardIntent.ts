/** The LLM interprets the request in context; application code validates the plan. */
export interface WizardIntent {
  kind: 'conversation' | 'clarification' | 'action'
  goal: string
  question: string
  execution: 'none' | 'prepare' | 'run'
}

export const WIZARD_INTENT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    kind: { type: 'string', enum: ['conversation', 'clarification', 'action'] },
    goal: { type: 'string', minLength: 1, maxLength: 2_000 },
    question: { type: 'string', maxLength: 2_000 },
    execution: { type: 'string', enum: ['none', 'prepare', 'run'] },
  },
  required: ['kind', 'goal', 'question', 'execution'],
}

export function parseWizardIntent(value: unknown): WizardIntent | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as Record<string, unknown>
  if (raw.kind !== 'conversation' && raw.kind !== 'clarification' && raw.kind !== 'action') return null
  if (typeof raw.goal !== 'string' || !raw.goal.trim() || raw.goal.length > 2_000) return null
  if (typeof raw.question !== 'string' || raw.question.length > 2_000) return null
  if (raw.kind === 'clarification' && !raw.question.trim()) return null
  if (raw.execution !== 'none' && raw.execution !== 'prepare' && raw.execution !== 'run') return null
  if (raw.kind === 'action' && raw.execution === 'none') return null
  // Conversation and clarification never authorize work. Normalize redundant
  // model fields conservatively instead of losing a useful follow-up question.
  return {
    kind: raw.kind,
    goal: raw.goal.trim(),
    question: raw.kind === 'clarification' ? raw.question.trim() : '',
    execution: raw.kind === 'action' ? raw.execution as 'prepare' | 'run' : 'none',
  }
}
