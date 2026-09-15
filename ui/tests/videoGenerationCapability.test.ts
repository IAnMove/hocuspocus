import assert from 'node:assert/strict'
import test from 'node:test'

import {
  VIDEO_GENERATION_OPERATION,
  VIDEO_MODEL_TYPES,
  alignWanT2vFrames,
  buildVideoGenerationCommand,
  effectiveVideoRequestsMatch,
  framesFromDurationSeconds,
  mcpArgumentsFromCommand,
  registerVideoGenerationCapability,
  resolveVideoGenerationAction,
  validateVideoGenerationAction,
  videoGenerationCapability,
  videoGenerationPresentation,
} from '../src/features/agent/videoGenerationCapability.ts'

function raw(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
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
    ...overrides,
  }
}

test('capability publishes destination and closed Wan T2V parameters', () => {
  assert.equal(videoGenerationCapability.name, 'generation_video')
  assert.equal(videoGenerationCapability.presentation.destination, 'studio')
  assert.deepEqual(videoGenerationCapability.presentation.anchors, ['video', 'generate', 'destination'])
  assert.equal(videoGenerationCapability.inputSchema.additionalProperties, false)
  assert.deepEqual(videoGenerationCapability.inputSchema.properties.model_type.enum, [...VIDEO_MODEL_TYPES])
  const collected: Array<{ name: string }> = []
  registerVideoGenerationCapability(definition => {
    collected.push(definition)
    return definition
  })
  assert.equal(collected[0]?.name, 'generation_video')
})

test('resolve fills effective Wan T2V values and keeps the literal prompt', () => {
  const action = resolveVideoGenerationAction(raw({
    model_type: undefined,
    resolution: undefined,
    video_length: undefined,
    duration_seconds: 5,
  }))
  assert.ok(action)
  assert.equal(action.prompt, '  A lantern over wet cobblestones.\n"Mañana"  ')
  assert.equal(action.modelType, 't2v_1.3B')
  assert.equal(action.resolution, '832x480')
  assert.equal(action.videoLength, 81)
  assert.equal(framesFromDurationSeconds(5), 81)
  assert.equal(alignWanT2vFrames(80), 81)
  assert.deepEqual(validateVideoGenerationAction(action), [])
  const presentation = videoGenerationPresentation(action)
  assert.equal(presentation.destination, 'studio')
  assert.equal(presentation.workspace, 'video-test')
  assert.equal(presentation.modelType, 't2v_1.3B')
  assert.equal(presentation.videoLength, 81)
})

test('resolve rejects other families, host paths and missing confirmation', () => {
  assert.equal(resolveVideoGenerationAction(raw({ confirm: false })), null)
  assert.equal(resolveVideoGenerationAction(raw({ model_type: 't2v_2_2' })), null)
  assert.equal(resolveVideoGenerationAction(raw({ model_type: 'minimax_h3' })), null)
  assert.equal(resolveVideoGenerationAction(raw({ image_start: '/tmp/frame.png' })), null)
  assert.equal(resolveVideoGenerationAction(raw({ workspace: 'bad workspace' })), null)
})

test('builder emits the MCP envelope without rewriting the prompt', () => {
  const action = resolveVideoGenerationAction(raw({
    image_start: '/api/v1/file/frame.png?workspace=source',
    workspace_collection_id: 'collection-a',
    negative_prompt: ' blur ',
  }))
  assert.ok(action)
  const command = buildVideoGenerationCommand(action)
  assert.equal(command.operation, VIDEO_GENERATION_OPERATION)
  assert.equal(command.version, 2)
  assert.equal(command.input.params.prompt, action.prompt)
  assert.equal(command.input.params.generation_mode, 'video')
  assert.equal(command.input.params.image_mode, 0)
  assert.equal(command.input.params.multi_prompts_gen_type, 2)
  assert.equal(command.input.workspace_collection_id, 'collection-a')
  const mcp = mcpArgumentsFromCommand(command)
  assert.equal('operation' in mcp, false)
  assert.ok(effectiveVideoRequestsMatch(command, mcp))
  assert.throws(
    () => buildVideoGenerationCommand({ ...action, prompt: '   ' }),
    /prompt/,
  )
})
