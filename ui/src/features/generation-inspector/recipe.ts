import { redactSecrets } from '../../lib/generationRecord'
import { fieldValue, known, UNKNOWN } from './fields'
import type { AttemptDiff, AttemptDiffField, CanonicalRef, InspectedAttempt, PortableRecipe, StoredField } from './types'

const RECIPE_PARAM_KEYS = [
  'resolution', 'video_length', 'num_inference_steps', 'guidance_scale',
  'negative_prompt', 'flow_shift', 'guidance_phases', 'alt_prompt',
  'sliding_window_size', 'sliding_window_overlap', 'self_refiner_setting',
  'stage2_steps', 'stg_scale', 'cfg_rescale', 'modality_scale',
  'use_gradient_estimation', 'ge_gamma', 'ge_alpha', 'progressive_pipeline',
  'single_stage_pipeline', 'progressive_stage1_image_weight',
  'progressive_stage2_steps', 'progressive_stage2_sigma',
  'progressive_stage3_steps', 'progressive_stage3_sigma',
  'progressive_stage3_image_weight', 'keyframe_conditioning_mode',
  'keyframe_inject_mode',
] as const

function pickParams(params: Record<string, unknown>): Record<string, unknown> {
  const next: Record<string, unknown> = {}
  for (const key of RECIPE_PARAM_KEYS) {
    if (key in params && params[key] != null) next[key] = params[key]
  }
  return redactSecrets(next) as Record<string, unknown>
}

function recipeLoras(params: Record<string, unknown>): PortableRecipe['loras'] {
  const raw = params.loras
  if (!Array.isArray(raw)) return []
  return raw.flatMap(item => {
    if (!item || typeof item !== 'object') return []
    const entry = item as { filename?: unknown; multiplier?: unknown }
    if (typeof entry.filename !== 'string' || !entry.filename.trim()) return []
    const multiplier = typeof entry.multiplier === 'number' || typeof entry.multiplier === 'string'
      ? entry.multiplier
      : 1
    return [{ filename: entry.filename, multiplier }]
  })
}

function canonicalRefs(refs: CanonicalRef[]): CanonicalRef[] {
  return refs.map(ref => ({
    role: ref.role,
    assetId: ref.assetId,
    filename: ref.filename,
    workspace: ref.workspace,
    uri: ref.uri,
    missing: ref.missing,
  }))
}

function promptExample(attempt: InspectedAttempt): string {
  if (attempt.originalPrompt.known) return attempt.originalPrompt.value
  if (attempt.effectivePrompt.known) return attempt.effectivePrompt.value
  return ''
}

export function copyRecipe(attempt: InspectedAttempt, name: string): PortableRecipe {
  return {
    recipe_version: 1,
    name: name.trim() || attempt.attemptId,
    mode: attempt.mode || attempt.product || 'video',
    model_type: fieldValue(attempt.model.id) || '',
    prompt_example: promptExample(attempt),
    params: pickParams(attempt.params),
    refs: canonicalRefs(attempt.refs),
    loras: recipeLoras(attempt.params),
  }
}

export function recipeIsPortable(recipe: PortableRecipe): boolean {
  const json = JSON.stringify(recipe)
  if (json.includes('do-not-save') || json.includes('Bearer ')) return false
  return recipe.refs.every(ref => !ref.uri || ref.uri.startsWith('/api/v1/') || !ref.uri.includes('://'))
}

function fieldAt(attempt: InspectedAttempt, path: string): StoredField<unknown> {
  if (path === 'originalPrompt') return attempt.originalPrompt
  if (path === 'effectivePrompt') return attempt.effectivePrompt
  if (path === 'negativePrompt') return attempt.negativePrompt
  if (path === 'model.id') return attempt.model.id
  if (path === 'model.version') return attempt.model.version
  if (path === 'model.provider') return attempt.model.provider
  if (path === 'intentId') return attempt.intentId
  if (path.startsWith('params.')) {
    const key = path.slice('params.'.length)
    if (Object.prototype.hasOwnProperty.call(attempt.params, key)) return known(attempt.params[key])
    return UNKNOWN
  }
  return UNKNOWN
}

function sameStored(left: StoredField<unknown>, right: StoredField<unknown>): boolean {
  if (left.known !== right.known) return false
  if (!left.known) return true
  return JSON.stringify(left.value) === JSON.stringify((right as { known: true; value: unknown }).value)
}

const COMPARE_PATHS = [
  'originalPrompt', 'effectivePrompt', 'negativePrompt',
  'model.id', 'model.version', 'model.provider', 'intentId',
]

export function compareAttempts(left: InspectedAttempt, right: InspectedAttempt): AttemptDiff {
  const keys = new Set([...Object.keys(left.params), ...Object.keys(right.params)])
  const paths = [...COMPARE_PATHS, ...[...keys].sort().map(key => `params.${key}`)]
  const fields: AttemptDiffField[] = paths.map(path => {
    const leftField = fieldAt(left, path)
    const rightField = fieldAt(right, path)
    return { path, left: leftField, right: rightField, changed: !sameStored(leftField, rightField) }
  })
  return { leftId: left.attemptId, rightId: right.attemptId, fields }
}
