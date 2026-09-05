import assert from 'node:assert/strict'
import test from 'node:test'

async function contract() {
  return import('../src/features/agent/commandContract.ts')
}

test('entity and artifact references normalize IDs and reject empty or cross-workspace values', async () => {
  const {
    normalizeEntityRef, normalizeArtifactRef, validateEntityRef, assertWorkspaceScope,
  } = await contract()

  assert.deepEqual(normalizeEntityRef({ kind: ' story ', id: ' story-1 ', workspaceId: ' room ', version: 2 }), {
    kind: 'story', id: 'story-1', workspaceId: 'room', version: 2,
  })
  assert.equal(validateEntityRef({ kind: 'story', id: '', workspaceId: 'room' }).length, 1)
  assert.throws(
    () => normalizeEntityRef({ kind: 'story', id: 'story-1', workspaceId: 'other' }, 'room'),
    error => error.code === 'cross_workspace_reference',
  )

  const artifact = normalizeArtifactRef({
    id: ' wav-1 ', kind: 'audio',
    owner: { kind: 'cue', id: 'cue-1', workspaceId: 'room' },
    taskId: ' task-1 ', uri: 'outputs/song.wav', metadata: { z: 1 },
  }, 'room')
  assert.equal(artifact.id, 'wav-1')
  assert.equal(artifact.owner.workspaceId, 'room')
  assert.throws(
    () => normalizeArtifactRef({
      id: 'wav-2', kind: 'audio',
      owner: { kind: 'cue', id: 'cue-2', workspaceId: 'other' }, uri: 'outputs/other.wav',
    }, 'room'),
    error => error.code === 'cross_workspace_reference',
  )
  assert.throws(
    () => assertWorkspaceScope('room', [artifact, { kind: 'story', id: 'story-1', workspaceId: 'other' }]),
    error => error.code === 'cross_workspace_reference',
  )
})

test('idempotency keys are stable across object insertion order and include target identity', async () => {
  const { buildIdempotencyKey, idempotencyKey, stableSerialize } = await contract()
  const target = { kind: 'story', id: 'story-1', workspaceId: 'room' }
  const left = buildIdempotencyKey({
    workspaceId: 'room', capability: 'create_story', target,
    input: { title: 'A', options: { b: 2, a: 1 } },
  })
  const right = idempotencyKey({
    workspaceId: ' room ', capability: 'create_story', target,
    input: { options: { a: 1, b: 2 }, title: 'A' },
  })
  assert.equal(left, right)
  assert.match(left, /^command:/)
  assert.notEqual(left, buildIdempotencyKey({
    workspaceId: 'room', capability: 'create_story', target: { ...target, id: 'story-2' },
    input: { title: 'A', options: { b: 2, a: 1 } },
  }))
  assert.equal(stableSerialize({ b: 2, a: 1 }), '{"a":1,"b":2}')
  assert.throws(
    () => buildIdempotencyKey({ workspaceId: 'room', capability: 'create_story', target: { ...target, id: '' }, input: {} }),
    error => error.code === 'empty_id',
  )
  assert.throws(
    () => buildIdempotencyKey({ workspaceId: 'room', capability: 'create_story', target: { ...target, workspaceId: 'other' }, input: {} }),
    error => error.code === 'cross_workspace_reference',
  )
})

test('JSON boundary rejects values the transport cannot reproduce and clones accepted payloads', async () => {
  const { buildIdempotencyKey, createCommandEnvelope, stableSerialize, normalizeArtifactRef } = await contract()
  const input = { nested: { value: 'before' }, optional: undefined, list: [, undefined, 'ok'] }
  const envelope = createCommandEnvelope({
    commandId: 'cmd-json', capability: 'draft_story', workspaceId: 'room', actor: 'wizard', input,
  })
  input.nested.value = 'after'
  assert.deepEqual(envelope.input, { nested: { value: 'before' }, list: [null, null, 'ok'] })
  assert.equal(
    envelope.idempotencyKey,
    buildIdempotencyKey({ workspaceId: 'room', capability: 'draft_story', input: { nested: { value: 'before' }, list: [null, null, 'ok'] } }),
  )
  assert.equal(stableSerialize({ list: [, undefined] }), '{"list":[null,null]}')

  const circular = {}
  circular.self = circular
  assert.throws(
    () => buildIdempotencyKey({ workspaceId: 'room', capability: 'draft_story', input: circular }),
    error => error.code === 'circular_json_value',
  )
  assert.throws(
    () => buildIdempotencyKey({ workspaceId: 'room', capability: 'draft_story', input: { when: new Date() } }),
    error => error.code === 'invalid_json_value',
  )
  assert.throws(
    () => stableSerialize({ amount: Number.NaN }),
    error => error.code === 'invalid_json_value',
  )
  assert.throws(
    () => normalizeArtifactRef({
      id: 'audio-1', kind: 'audio',
      owner: { kind: 'cue', id: 'cue-1', workspaceId: 'room' },
      uri: 'outputs/song.wav', metadata: { callback: () => undefined },
    }),
    error => error.code === 'invalid_json_value',
  )
})

test('command envelopes compute and verify the canonical idempotency key', async () => {
  const {
    createCommandEnvelope, normalizeCommandEnvelope, serializeCommand, validateCommandEnvelope,
    buildIdempotencyKey,
  } = await contract()
  const input = {
    commandId: 'cmd-1', capability: 'generate_story_song', workspaceId: 'room', actor: 'wizard',
    target: { kind: 'story', id: 'story-1', workspaceId: 'room' },
    input: { lyrics: 'Verso', model: 'ace_step' },
    presentation: { navigationTarget: { destination: 'story_lab', section: 'music' }, anchors: ['lyrics'], speed: 'normal' },
  }
  const envelope = createCommandEnvelope(input)
  assert.equal(envelope.idempotencyKey, buildIdempotencyKey(input))
  assert.equal(validateCommandEnvelope(envelope).length, 0)
  assert.equal(serializeCommand(envelope), serializeCommand(normalizeCommandEnvelope(envelope)))
  assert.throws(
    () => normalizeCommandEnvelope({ ...envelope, idempotencyKey: 'manually-reused-for-other-input' }),
    error => error.code === 'idempotency_key_mismatch',
  )
  assert.throws(
    () => normalizeCommandEnvelope({ ...input, target: { ...input.target, workspaceId: 'other' } }),
    error => error.code === 'cross_workspace_reference',
  )
})

test('presentation aliases normalize to a semantic navigation plan without DOM selectors', async () => {
  const {
    normalizeNavigationTarget, normalizePresentationPlan, presentationPlanFromCapabilityPresentation,
  } = await contract()
  assert.deepEqual(normalizeNavigationTarget({ tab: 'story_lab', section: 'music', anchor: 'lyrics' }), {
    destination: 'story_lab', section: 'music', anchor: 'lyrics',
  })
  assert.deepEqual(normalizePresentationPlan({
    destination: 'studio', section: 'video', anchors: ['prompt', 'prompt'], focus: 'prompt', speed: 'theatrical',
  }), {
    navigationTarget: { destination: 'studio', section: 'video' },
    anchors: ['prompt'], focus: 'prompt', speed: 'theatrical',
  })
  assert.deepEqual(presentationPlanFromCapabilityPresentation({
    destination: 'video_3d', anchors: ['scene'], replay: 'atomic',
  }), {
    navigationTarget: { destination: 'video_3d' }, anchors: ['scene'], speed: 'normal', replay: 'atomic',
  })
})

test('command results accept only canonical states and preserve IDs/artifacts/errors', async () => {
  const {
    COMMAND_STATUSES, normalizeCommandResult, serializeCommandResult, validateCommandResult,
  } = await contract()
  for (const status of COMMAND_STATUSES) {
    const result = normalizeCommandResult({ commandId: `cmd-${status}`, status, taskIds: ['task-1', 'task-1'], pipelineIds: [] }, 'room')
    assert.equal(result.status, status)
    assert.deepEqual(result.taskIds, ['task-1'])
  }
  const result = normalizeCommandResult({
    commandId: 'cmd-final', status: 'partial',
    entities: [{ kind: 'story', id: 'story-1', workspaceId: 'room' }],
    artifacts: [{
      id: 'video-1', kind: 'video', uri: 'outputs/video.mp4',
      owner: { kind: 'production', id: 'production-1', workspaceId: 'room' },
    }],
    taskIds: ['task-1'], pipelineIds: ['pipeline-1'],
    navigationTarget: { destination: 'director', entity: { kind: 'production', id: 'production-1', workspaceId: 'room' } },
    error: { code: 'provider_timeout', message: 'Reintentar.', retryable: true, details: { attempt: 2 } },
  }, 'room')
  assert.equal(result.error?.retryable, true)
  assert.equal(result.artifacts[0].owner.workspaceId, 'room')
  assert.match(serializeCommandResult(result, 'room'), /provider_timeout/)
  assert.equal(validateCommandResult({ commandId: 'cmd-bad', status: 'running' }, 'room').length, 1)
  assert.throws(
    () => normalizeCommandResult({
      commandId: 'cmd-cross', status: 'completed',
      entities: [
        { kind: 'story', id: 'story-1', workspaceId: 'room' },
        { kind: 'story', id: 'story-2', workspaceId: 'other' },
      ],
    }),
    error => error.code === 'cross_workspace_reference',
  )
  assert.throws(
    () => normalizeCommandResult({ commandId: 'cmd-empty', status: 'completed', taskIds: [''] }, 'room'),
    error => error.code === 'empty_id',
  )
  assert.throws(
    () => normalizeCommandResult({
      commandId: 'cmd-error', status: 'failed', error: { code: 'bad', message: 'No', retryable: 'true' },
    }, 'room'),
    error => error.code === 'invalid_boolean',
  )
})
