import assert from 'node:assert/strict'
import test from 'node:test'
import { JSDOM } from 'jsdom'
import {
  attemptFromOpenRequest,
  belongsToFolder,
  catalogFromOutputs,
  compareAttempts,
  copyRecipe,
  inspectAttempt,
  keptIntent,
  loadInspectedAttempt,
  matchCatalog,
  persistInspectedAttempt,
  planClone,
  planRetry,
  preflightGenerate,
  recipeIsPortable,
  resolveRef,
} from '../src/features/generation-inspector/index.ts'
import { clearInspectedAttempt } from '../src/features/generation-inspector/persistence.ts'

function installDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { url: 'http://localhost/' })
  Object.assign(globalThis, {
    window: dom.window,
    document: dom.window.document,
    CustomEvent: dom.window.CustomEvent,
    Event: dom.window.Event,
  })
}

installDom()

const transformed = {
  generation_id: 'gen_choir',
  output_folder: 'night-shift',
  workspace_id: 'collection-a',
  prompt_original: 'user choir',
  prompt_effective: 'cinematic choir, night',
  negative_prompt: 'blur',
  intent_id: 'intent-choir',
  correlations: { command_id: 'intent-choir' },
  model: { provider: 'local', id: 'flux2', version: 'r1' },
  params: {
    resolution: '720p',
    image_refs: [{ asset_id: 'asset_gone', filename: 'hero.png', workspace: 'night-shift' }],
    api_key: 'do-not-save',
  },
  transforms: [{
    source: 'guide',
    field: 'prompt',
    before: 'user choir',
    after: 'cinematic choir, night',
  }],
}

const catalog = [
  { assetId: 'asset_first', filename: 'first.png', workspace: 'night-shift' },
  { assetId: 'asset_hero', filename: 'hero.png', workspace: 'other-folder' },
]

test('original and effective prompts differ when a stored transform happened', () => {
  const attempt = inspectAttempt(transformed, { workspace: 'night-shift' })
  assert.equal(attempt.originalPrompt.known, true)
  assert.equal(attempt.effectivePrompt.known, true)
  if (!attempt.originalPrompt.known || !attempt.effectivePrompt.known) return
  assert.notEqual(attempt.originalPrompt.value, attempt.effectivePrompt.value)
  assert.equal(attempt.originalPrompt.value, 'user choir')
  assert.equal(attempt.effectivePrompt.value, 'cinematic choir, night')
  assert.equal(attempt.changes[0]?.source, 'guide')
})

test('does not reconstruct original from output or from effective-only storage', () => {
  const attempt = inspectAttempt({
    output_folder: 'night-shift',
    prompt_effective: 'cinematic choir, night',
    prompt_full: 'cinematic choir, night',
    output: { caption: 'a choir singing on stage' },
    result: { text: 'a choir singing on stage' },
  }, { workspace: 'night-shift' })
  assert.equal(attempt.originalPrompt.known, false)
  assert.equal(attempt.effectivePrompt.known, true)
  if (attempt.effectivePrompt.known) assert.equal(attempt.effectivePrompt.value, 'cinematic choir, night')
  assert.equal(JSON.stringify(attempt).includes('a choir singing on stage'), false)
})

test('prompt history authored text is original and leaves effective unknown', () => {
  const attempt = inspectAttempt({
    id: 'prompt-1',
    prompt: 'typed by the user',
    negativePrompt: '',
    mode: 'image',
    model: 'flux2',
    workspace: 'night-shift',
    source: 'generation',
    createdAt: '2026-09-11T00:00:00Z',
  }, { workspace: 'night-shift' })
  assert.equal(attempt.originalPrompt.known, true)
  if (attempt.originalPrompt.known) assert.equal(attempt.originalPrompt.value, 'typed by the user')
  assert.equal(attempt.effectivePrompt.known, false)
})

test('clone mints a new intent and transport retry keeps the stored intent', () => {
  const attempt = inspectAttempt(transformed, { workspace: 'night-shift', catalog })
  let n = 0
  const mint = (prefix: string) => `${prefix}_${++n}`
  const cloned = planClone(attempt, { workspace: 'night-shift', catalog, mint })
  const retried = planRetry(attempt, { workspace: 'night-shift', catalog, mint })
  assert.equal(cloned.kind, 'clone')
  assert.notEqual(cloned.intentId, 'intent-choir')
  assert.equal(cloned.generationId.startsWith('gen_'), true)
  assert.notEqual(cloned.generationId, attempt.generationId)
  assert.equal(retried.kind, 'retry')
  assert.equal(retried.intentId, 'intent-choir')
  assert.equal(keptIntent(retried, attempt), true)
  assert.equal(keptIntent(cloned, attempt), false)
  assert.notEqual(retried.generationId, cloned.generationId)
})

test('missing refs stay missing and are not replaced by the first catalog item', () => {
  const attempt = inspectAttempt(transformed, { workspace: 'night-shift', catalog })
  assert.equal(attempt.refs[0]?.assetId, 'asset_gone')
  assert.equal(attempt.refs[0]?.missing, true)
  assert.notEqual(attempt.refs[0]?.assetId, catalog[0].assetId)
  const cloned = planClone(attempt, { workspace: 'night-shift', catalog, mint: prefix => `${prefix}_x` })
  assert.equal(cloned.refs[0]?.assetId, 'asset_gone')
  assert.equal(cloned.refs[0]?.missing, true)
  assert.equal(cloned.refs[0]?.filename, 'hero.png')
  assert.notEqual(cloned.refs[0]?.assetId, catalog[0].assetId)
  assert.equal(matchCatalog(cloned.refs[0], catalog), undefined)
})

test('preflight blocks generate when refs are missing or the prompt is unknown', () => {
  const attempt = inspectAttempt(transformed, { workspace: 'night-shift', catalog })
  const cloned = planClone(attempt, { workspace: 'night-shift', catalog, mint: prefix => `${prefix}_p` })
  const blocked = preflightGenerate(cloned, { workspace: 'night-shift', catalog })
  assert.equal(blocked.ok, false)
  assert.ok(blocked.issues.some(issue => issue.code === 'missing_ref' && issue.blocking))
  const empty = inspectAttempt({ output_folder: 'night-shift' }, { workspace: 'night-shift' })
  const emptyPlan = planClone(empty, { workspace: 'night-shift', mint: prefix => `${prefix}_e` })
  const emptyReport = preflightGenerate(emptyPlan, { workspace: 'night-shift' })
  assert.equal(emptyReport.ok, false)
  assert.ok(emptyReport.issues.some(issue => issue.code === 'empty_prompt' && issue.blocking))
})

test('warns when the live model or version differs', () => {
  const attempt = inspectAttempt(transformed, { workspace: 'night-shift' })
  const cloned = planClone(attempt, {
    workspace: 'night-shift',
    currentModel: { id: 'qwen', version: 'r9' },
    mint: prefix => `${prefix}_m`,
  })
  assert.ok(cloned.warnings.some(item => item.code === 'model_mismatch'))
  assert.ok(cloned.warnings.some(item => item.code === 'version_mismatch'))
})

test('reload keeps the inspected attempt and a workspace switch does not leak another folder', () => {
  const attempt = inspectAttempt(transformed, { workspace: 'night-shift' })
  persistInspectedAttempt('night-shift', attempt, true)
  const restored = loadInspectedAttempt('night-shift')
  assert.equal(restored?.attemptId, 'gen_choir')
  assert.equal(restored?.attempt.originalPrompt.known && restored.attempt.originalPrompt.value, 'user choir')
  assert.equal(loadInspectedAttempt('other-folder'), null)
  assert.equal(belongsToFolder(attempt, 'other-folder'), false)
  const foreign = inspectAttempt({ ...transformed, output_folder: 'other-folder' }, { workspace: 'other-folder' })
  assert.equal(persistInspectedAttempt('night-shift', foreign), null)
  assert.equal(loadInspectedAttempt('night-shift')?.attempt.outputFolder, 'night-shift')
  assert.equal(attemptFromOpenRequest({ workspace: 'night-shift', source: { ...transformed, output_folder: 'other-folder' } }), null)
  assert.equal(attemptFromOpenRequest({ workspace: 'night-shift', attempt: foreign }), null)
  clearInspectedAttempt('night-shift')
})

test('copies a recipe with canonical refs and without secrets', () => {
  const attempt = inspectAttempt(transformed, { workspace: 'night-shift', catalog })
  const recipe = copyRecipe(attempt, 'Choir night')
  assert.equal(recipe.recipe_version, 1)
  assert.equal(recipe.model_type, 'flux2')
  assert.equal(recipe.prompt_example, 'user choir')
  assert.equal(recipe.params.resolution, '720p')
  assert.equal('api_key' in recipe.params, false)
  assert.equal(JSON.stringify(recipe).includes('do-not-save'), false)
  assert.equal(recipe.refs[0]?.assetId, 'asset_gone')
  assert.equal(recipe.refs[0]?.filename, 'hero.png')
  assert.equal(recipeIsPortable(recipe), true)
})

test('compare two attempts surfaces stored prompt and model differences', () => {
  const left = inspectAttempt(transformed, { workspace: 'night-shift' })
  const right = inspectAttempt({
    ...transformed,
    generation_id: 'gen_choir_2',
    prompt_effective: 'metal choir',
    model: { provider: 'local', id: 'qwen', version: 'r2' },
  }, { workspace: 'night-shift' })
  const diff = compareAttempts(left, right)
  assert.ok(diff.fields.some(field => field.path === 'effectivePrompt' && field.changed))
  assert.ok(diff.fields.some(field => field.path === 'model.id' && field.changed))
  assert.equal(diff.fields.find(field => field.path === 'originalPrompt')?.changed, false)
})

test('catalog mapping never invents the first item for an unmatched filename', () => {
  const items = catalogFromOutputs([
    { name: 'first.png', asset_id: 'asset_first', workspace_id: 'night-shift' },
  ])
  const missing = resolveRef({
    role: 'image_refs', assetId: 'asset_gone', filename: 'hero.png',
    workspace: 'night-shift', uri: null, missing: false,
  }, items)
  assert.equal(missing.missing, true)
  assert.equal(missing.assetId, 'asset_gone')
  assert.notEqual(missing.assetId, items[0].assetId)
})
