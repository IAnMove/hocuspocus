import { fieldValue, mintId } from './fields'
import { resolveRef } from './refs'
import type {
  CanonicalRef, CloneEnvironment, ClonePlan, CloneWarning, InspectedAttempt,
  InspectedModel, PreflightIssue, PreflightReport, StoredField,
} from './types'

function nextId(prefix: string, mint?: (prefix: string) => string): string {
  return mint ? mint(prefix) : mintId(prefix)
}

function storedText(field: StoredField<string>): string {
  return field.known ? field.value : ''
}

function clonePrompt(attempt: InspectedAttempt): string {
  if (attempt.originalPrompt.known) return attempt.originalPrompt.value
  if (attempt.effectivePrompt.known) return attempt.effectivePrompt.value
  return ''
}

function modelToken(field: StoredField<string | null>): string {
  if (!field.known || !field.value) return ''
  return field.value
}

function modelWarnings(attempt: InspectedAttempt, env: CloneEnvironment): CloneWarning[] {
  const current = env.currentModel
  if (!current) return []
  const warnings: CloneWarning[] = []
  const modelId = modelToken(attempt.model.id)
  const version = modelToken(attempt.model.version)
  if (current.id && modelId && current.id !== modelId) {
    warnings.push({ code: 'model_mismatch', message: 'model_mismatch' })
  }
  if (current.version && version && current.version !== version) {
    warnings.push({ code: 'version_mismatch', message: 'version_mismatch' })
  }
  return warnings
}

function unknownWarnings(attempt: InspectedAttempt): CloneWarning[] {
  const warnings: CloneWarning[] = []
  if (!attempt.originalPrompt.known) warnings.push({ code: 'unknown_field', message: 'unknown_field', field: 'originalPrompt' })
  if (!attempt.effectivePrompt.known) warnings.push({ code: 'unknown_field', message: 'unknown_field', field: 'effectivePrompt' })
  return warnings
}

function bindRefs(refs: CanonicalRef[], env: CloneEnvironment): CanonicalRef[] {
  return refs.map(ref => resolveRef(ref, env.catalog || []))
}

function missingWarnings(refs: CanonicalRef[]): CloneWarning[] {
  return refs.filter(ref => ref.missing).map(ref => ({
    code: 'missing_ref' as const,
    message: 'missing_ref',
    role: ref.role,
  }))
}

function planFor(
  kind: ClonePlan['kind'],
  attempt: InspectedAttempt,
  env: CloneEnvironment,
  intentId: string,
  intentKnown: boolean,
): ClonePlan {
  const refs = bindRefs(attempt.refs, env)
  return {
    kind,
    intentId,
    intentKnown,
    generationId: nextId('gen', env.mint),
    parentAttemptId: attempt.attemptId,
    outputFolder: attempt.outputFolder,
    prompt: clonePrompt(attempt),
    negativePrompt: storedText(attempt.negativePrompt),
    params: { ...attempt.params },
    refs,
    model: attempt.model,
    warnings: [...modelWarnings(attempt, env), ...unknownWarnings(attempt), ...missingWarnings(refs)],
  }
}

export function planClone(attempt: InspectedAttempt, env: CloneEnvironment): ClonePlan {
  return planFor('clone', attempt, env, nextId('intent', env.mint), true)
}

export function planRetry(attempt: InspectedAttempt, env: CloneEnvironment): ClonePlan {
  const intentId = storedText(attempt.intentId)
  return planFor('retry', attempt, env, intentId, attempt.intentId.known)
}

function issueFromWarning(warning: CloneWarning): PreflightIssue {
  return { code: warning.code, message: warning.message, blocking: false, role: warning.role, field: warning.field }
}

export function preflightGenerate(plan: ClonePlan, env: CloneEnvironment): PreflightReport {
  const issues: PreflightIssue[] = plan.warnings.map(issueFromWarning)
  if (!plan.prompt.trim()) {
    issues.push({ code: 'empty_prompt', message: 'empty_prompt', blocking: true })
  }
  if (plan.outputFolder && env.workspace && plan.outputFolder !== env.workspace) {
    issues.push({ code: 'workspace_mismatch', message: 'workspace_mismatch', blocking: true })
  }
  for (const ref of plan.refs) {
    if (ref.missing) issues.push({ code: 'missing_ref', message: 'missing_ref', blocking: true, role: ref.role })
  }
  return { ok: issues.every(issue => !issue.blocking), issues }
}

export function modelKnown(model: InspectedModel): { id: string; version: string; provider: string } {
  return {
    id: fieldValue(model.id) || '',
    version: fieldValue(model.version) || '',
    provider: fieldValue(model.provider) || '',
  }
}

export function keptIntent(plan: ClonePlan, parent: InspectedAttempt): boolean {
  if (plan.kind !== 'retry') return false
  if (!parent.intentId.known) return plan.intentId === ''
  return plan.intentId === parent.intentId.value
}
