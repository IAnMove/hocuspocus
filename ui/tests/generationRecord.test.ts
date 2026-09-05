import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ATTEMPT_IDENTITY_POLICY,
  GENERATION_RECORD_AUTHORITY,
  GENERATION_RECORD_SCHEMA,
  PROMPT_DISPLAY_MAX,
  applyCancel,
  isHostPath,
  isLegalGenerationTransition,
  mapAssetManifestStatus,
  mapGenerationProduct,
  mapGenerationStatusToManifest,
  mergeGenerationRecord,
  portableFilename,
  projectFromAssetManifest,
  recordBelongsToWorkspace,
  redactSecrets,
  requestCancel,
  resumeGenerationRecord,
  retryGeneration,
  toAssetManifestPatch,
  truncatePromptDisplay,
  type GenerationRecord,
} from '../src/lib/generationRecord.ts'

const sample: GenerationRecord = projectFromAssetManifest({
  asset: { id: 'asset_video_1', filename: 'choir.mp4' },
  origin: {
    tool: 'story_lab',
    capability: 'generate_story_song',
    workspace_id: 'collection-a',
    output_folder: 'night-shift',
    project: { kind: 'story', id: 'story_1' },
  },
  execution: {
    status: 'prepared',
    job_id: 'job-1',
    cue_id: 'cue-1',
    candidate_id: 'candidate-1',
    song_version: '2',
  },
  generation: {
    prompts: { effective: 'Metal fantástico de 1981', language: 'es' },
    model: { provider: 'local', id: 'minimax-h3', revision: 'r1' },
    parameters: { seed: 3, api_key: 'do-not-save', nested: { authorization: 'Bearer secret' } },
    inputs: [],
  },
  timing: { created_at: '2026-09-01T00:00:00Z' },
  lineage: {
    parents: [{ id: 'asset_song_1', kind: 'audio', uri: 'song.wav' }],
    transformations: [],
  },
  technical: { generation_id: 'gen_fixed' },
})

test('projects the generation-record contract from an asset manifest', () => {
  assert.equal(sample.schema, GENERATION_RECORD_SCHEMA)
  assert.equal(sample.generation_id, 'gen_fixed')
  assert.equal(sample.asset_id, 'asset_video_1')
  assert.equal(sample.product, 'story_lab')
  assert.equal(sample.status, 'planned')
  assert.equal(sample.workspace_id, 'collection-a')
  assert.equal(sample.output_folder, 'night-shift')
  assert.equal(sample.cue_id, 'cue-1')
  assert.equal(sample.location.filename, 'choir.mp4')
  assert.equal(sample.location.sidecar, 'choir.meta.json')
  assert.equal(sample.lineage.parents[0]?.asset_id, 'asset_song_1')
  assert.equal(mapGenerationStatusToManifest(sample.status), 'prepared')
  assert.equal(ATTEMPT_IDENTITY_POLICY, 'new_generation_id')
  assert.equal(GENERATION_RECORD_AUTHORITY, 'projection')
  assert.equal(sample.prompt_original, sample.prompt_effective)
  assert.equal('title' in sample, false)
})

test('truncates prompt_display and redacts secrets', () => {
  const longPrompt = 'α'.repeat(PROMPT_DISPLAY_MAX + 40)
  const display = truncatePromptDisplay(longPrompt)
  assert.equal(display.length <= PROMPT_DISPLAY_MAX, true)
  assert.equal(display.endsWith('…'), true)
  const redacted = redactSecrets({
    api_key: 'do-not-save',
    nested: { authorization: 'Bearer secret' },
    prompt: 'safe',
  }) as { api_key: string; nested: { authorization: string }; prompt: string }
  assert.equal(redacted.api_key, '[REDACTED]')
  assert.equal(redacted.nested.authorization, '[REDACTED]')
  assert.equal(redacted.prompt, 'safe')
  assert.equal(sample.model.configuration.api_key, '[REDACTED]')
  assert.notEqual(JSON.stringify(sample).includes('do-not-save'), true)
})

test('maps prepared and partial without a seventh public status', () => {
  assert.deepEqual(mapAssetManifestStatus('prepared'), {
    status: 'planned', resultKind: null, error: null,
  })
  assert.deepEqual(mapAssetManifestStatus('partial', true), {
    status: 'completed', resultKind: 'partial', error: null,
  })
  assert.equal(mapAssetManifestStatus('partial', false).status, 'failed')
  assert.equal(mapAssetManifestStatus('bogus').status, 'failed')
  assert.equal(mapAssetManifestStatus('bogus').error?.code, 'invalid_status')
  assert.equal(mapGenerationProduct('scene-animator-3d'), 'video_3d')
  assert.equal(mapGenerationProduct('spoofed', 'generate_story_song'), 'story_lab')
})

test('identity is generation_id/asset_id, never title or prompt', () => {
  const other = projectFromAssetManifest({
    asset: { id: 'asset_other', filename: 'choir.mp4' },
    origin: { tool: 'studio', workspace_id: 'collection-a', output_folder: 'night-shift' },
    execution: { status: 'queued', job_id: 'job-other' },
    generation: {
      prompts: { effective: sample.prompt_full },
      model: {},
      parameters: {},
      inputs: [],
    },
    lineage: { parents: [] },
  })
  assert.notEqual(other.generation_id, sample.generation_id)
  assert.notEqual(other.asset_id, sample.asset_id)
  assert.equal(other.prompt_full, sample.prompt_full)
})

test('retry mints a new generation_id and parent lineage', () => {
  const child = retryGeneration(sample)
  const sameBytes = retryGeneration(sample, true)
  const second = retryGeneration(sample)
  assert.notEqual(child.generation_id, sample.generation_id)
  assert.notEqual(second.generation_id, child.generation_id)
  assert.notEqual(child.asset_id, sample.asset_id)
  assert.equal(child.retry_count, 1)
  assert.equal(child.status, 'planned')
  assert.equal(child.lineage.parents[0]?.generation_id, sample.generation_id)
  assert.equal(sameBytes.asset_id, sample.asset_id)
  assert.notEqual(sameBytes.generation_id, sample.generation_id)
})

test('cancellation before running settles; during running waits for apply', () => {
  const queued = { ...sample, status: 'queued' as const }
  assert.equal(requestCancel(queued).status, 'cancelled')
  const running = { ...sample, status: 'running' as const }
  const requested = requestCancel(running)
  assert.equal(requested.status, 'running')
  assert.equal(requested.cancellation.requested, true)
  assert.equal(applyCancel(running).status, 'cancelled')
  assert.equal(applyCancel({ ...sample, status: 'completed' }).status, 'completed')
  assert.equal(applyCancel({ ...sample, status: 'failed' }).status, 'failed')
  assert.equal(isLegalGenerationTransition('running', 'completed'), true)
  assert.equal(isLegalGenerationTransition('completed', 'running'), false)
})

test('records cannot be adopted across workspaces and paths stay relative', () => {
  assert.equal(recordBelongsToWorkspace(sample, 'collection-a'), true)
  assert.equal(recordBelongsToWorkspace(sample, 'collection-b'), false)
  assert.equal(isHostPath('/tmp/outputs'), true)
  assert.equal(isHostPath('night-shift'), false)
  assert.equal(portableFilename('/tmp/outputs/choir.mp4'), 'choir.mp4')
  const patch = toAssetManifestPatch({
    ...sample,
    timestamps: { ...sample.timestamps, duration_ms: 4120 },
  })
  assert.equal((patch.timing as { total_ms: number }).total_ms, 4120)
  assert.equal((patch.origin as { workspace_id: string }).workspace_id, 'collection-a')
  assert.equal((patch.asset as { id: string }).id, 'asset_video_1')
  assert.equal(JSON.stringify(patch).includes('/tmp'), false)
})

test('does not invent a workspace collection from output_folder', () => {
  const loose = projectFromAssetManifest({
    asset: { id: 'asset_loose', filename: 'loose.mp4' },
    origin: { tool: 'studio', output_folder: 'night-shift' },
    execution: { status: 'queued', job_id: 'job-loose' },
    generation: { prompts: { original: 'user', effective: 'model' }, model: {}, parameters: {}, inputs: [] },
    lineage: { parents: [], transformations: [{ id: 'asset_src', kind: 'upscale' }] },
    timing: { queue_ms: 10, inference_ms: 20, total_ms: 30 },
  })
  assert.equal(loose.workspace_id, null)
  assert.equal(loose.output_folder, 'night-shift')
  assert.equal(recordBelongsToWorkspace(loose, 'night-shift'), false)
  assert.equal(loose.prompt_original, 'user')
  assert.equal(loose.prompt_effective, 'model')
  assert.equal(loose.prompt_full, 'model')
  assert.equal(loose.timestamps.queue_ms, 10)
  assert.equal(loose.lineage.transformations[0]?.asset_id, 'asset_src')
  const patch = toAssetManifestPatch(loose)
  assert.equal('workspace_id' in (patch.origin as object), false)
  assert.equal((patch.generation as { prompts: { original: string; effective: string } }).prompts.original, 'user')
  assert.equal((patch.generation as { prompts: { original: string; effective: string } }).prompts.effective, 'model')
  assert.equal((patch.lineage as { transformations: { id: string; kind: string }[] }).transformations[0].kind, 'upscale')
  assert.equal((patch.lineage as { transformations: { id: string }[] }).transformations[0].id, 'asset_src')
  assert.equal('asset_id' in (patch.lineage as { transformations: object[] }).transformations[0], false)
})

test('merge keeps lineage when the patch sends empty lists', () => {
  const merged = mergeGenerationRecord(sample, {
    prompt_full: 'updated',
    lineage: { parents: [], derivatives: [], transformations: [] },
  })
  assert.equal(merged.prompt_full, 'updated')
  assert.equal(merged.prompt_effective, 'updated')
  assert.equal(merged.prompt_display, 'updated')
  assert.equal(merged.lineage.parents[0]?.asset_id, 'asset_song_1')
  const extra = mergeGenerationRecord(merged, {
    lineage: { transformations: [{ id: 'asset_fx', kind: 'grade' }] },
  })
  assert.equal(extra.lineage.parents[0]?.asset_id, 'asset_song_1')
  assert.equal(extra.lineage.transformations[0]?.kind, 'grade')
})

test('resume of running marks reconciliation without inventing success', () => {
  const running = { ...sample, status: 'running' as const }
  const recovered = resumeGenerationRecord(running)
  assert.equal(recovered.status, 'running')
  assert.equal(recovered.reconciliation.needed, true)
  assert.equal(recovered.reconciliation.reason, 'interrupted')
  const alive = resumeGenerationRecord(running, true)
  assert.equal(alive.status, 'running')
  assert.equal(alive.reconciliation.needed, false)
})
