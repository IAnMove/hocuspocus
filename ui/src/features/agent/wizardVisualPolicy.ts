import type { AgentTurn } from './agentActions'
import { getCapability } from './capabilityRegistry'
import { isExpensiveAction } from './agentContract'
import { rejectedWizardAction, withWizardRejections } from './wizardTurnReport'

/** Validate the interpreted intent. Never infer or manufacture actions from words in the request. */
export function validateWizardPlan(hasVisualMedia: boolean, before: AgentTurn): AgentTurn {
  let after = before
  if (!before.intent) {
    after = { ...before, actions: [], rejections: [
      ...(before.rejections || []), rejectedWizardAction({ type: 'intent' }, 0, 'invalid_intent'),
    ] }
  } else if (hasVisualMedia || before.intent.kind === 'conversation') {
    // Visual analysis remains evidence only, as in the existing media contract.
    after = { ...before, actions: [] }
  } else if (before.intent.kind === 'clarification') {
    after = { ...before, actions: before.actions.filter(action =>
      action.type === 'open_tab' || action.type === 'open_story_section' || action.type === 'open_series_section') }
  } else if (before.intent.execution === 'prepare') {
    after = { ...before, actions: before.actions.filter(action => {
      const risk = getCapability(action.type)?.risk
      return risk !== 'compute' && risk !== 'external_cost' && !isExpensiveAction(action.type)
    }) }
  }
  return withWizardRejections(before, after, hasVisualMedia ? 'visual_evidence_only' : 'request_policy')
}
