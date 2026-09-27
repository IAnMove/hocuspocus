import assert from 'node:assert/strict'
import test from 'node:test'

import { createVideoGenerationAdapter } from '../src/features/agent/videoGenerationAdapter.ts'
import {
  VIDEO_GENERATION_OPERATION,
  buildVideoGenerationCommand,
  effectiveVideoRequestsMatch,
  mcpArgumentsFromCommand,
  resolveVideoGenerationAction,
} from '../src/features/agent/videoGenerationCapability.ts'

const originalFetch = globalThis.fetch

function action() {
  const resolved = resolveVideoGenerationAction({
    type: 'generation_video',
    intent_id: 'wizard-video-1',
    workspace: 'video-test',
    prompt: '  A lantern over wet cobblestones.\n"Mañana"  ',
    model_type: 't2v_1.3B',
    resolution: '832x480',
    video_length: 81,
    num_inference_steps: 30,
    guidance_scale: 5,
    seed: 42,
    confirm: true,
  })
  assert.ok(resolved)
  return resolved
}

function receipt(intentId = 'wizard-video-1') {
  return {
    version: 1,
    commandId: intentId,
    operation: VIDEO_GENERATION_OPERATION,
    status: 'queued',
    entities: [],
    artifacts: [],
    taskIds: ['task-video-1'],
    pipelineIds: [],
    result: {
      job_id: 'job-video-1',
      task_id: 'task-video-1',
      workspace: 'video-test',
      status: 'queued',
    },
    commandVersion: 2,
    fingerprintVersion: 2,
    contentFingerprint: 'a'.repeat(64),
  }
}

test.afterEach(() => {
  globalThis.fetch = originalFetch
})

test('adapter posts the same envelope MCP would send and reports destination', async () => {
  const posted: Array<{ url: string; body: Record<string, unknown>; headers: Headers }> = []
  const adapter = createVideoGenerationAdapter({
    fetch: async (input, init) => {
      posted.push({
        url: String(input),
        body: JSON.parse(String(init?.body)),
        headers: new Headers(init?.headers),
      })
      return new Response(JSON.stringify({ receipt: receipt(), replayed: false }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    },
  })
  const result = await adapter.submit(action())
  assert.equal(posted.length, 1)
  assert.match(posted[0].url, /\/api\/v1\/generation\/commands$/)
  assert.equal(posted[0].headers.get('X-Hocus-UI-Surface'), 'wizard')
  assert.equal(posted[0].body.operation, VIDEO_GENERATION_OPERATION)
  assert.equal(posted[0].body.input.params.prompt, action().prompt)
  assert.ok(effectiveVideoRequestsMatch(result.command, result.mcpArguments))
  assert.deepEqual(result.mcpArguments, mcpArgumentsFromCommand(buildVideoGenerationCommand(action())))
  assert.equal(result.presentation.destination, 'studio')
  assert.equal(result.presentation.workspace, 'video-test')
  assert.equal(result.presentation.modelType, 't2v_1.3B')
  assert.match(result.message, /video-test/)
  assert.equal(result.taskId, 'task-video-1')
  assert.equal(result.replayed, false)
})

test('adapter recovers a lost receipt without submitting again', async () => {
  const urls: string[] = []
  const adapter = createVideoGenerationAdapter({
    fetch: async input => {
      urls.push(String(input))
      return new Response(JSON.stringify({ receipt: receipt(), task: { status: 'queued' } }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      })
    },
  })
  const recovered = await adapter.recover('video-test', 'wizard-video-1')
  assert.equal(recovered.commandId, 'wizard-video-1')
  assert.match(urls[0], /intent_id=wizard-video-1/)
  assert.match(urls[0], /workspace=video-test/)
})

test('adapter surfaces parameter rejection without inventing a task', async () => {
  const adapter = createVideoGenerationAdapter({
    fetch: async () => new Response(JSON.stringify({
      detail: { code: 'invalid_command', message: 'Choose a registered Wan 2.1 Text2Video model' },
    }), { status: 422, headers: { 'content-type': 'application/json' } }),
  })
  await assert.rejects(adapter.submit(action()), /Wan 2.1 Text2Video/)
})
