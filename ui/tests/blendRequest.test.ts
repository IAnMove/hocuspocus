import assert from 'node:assert/strict'
import test from 'node:test'
import { buildBlendRequest, type BlendRequestState } from '../src/features/studio/blendRequest.ts'

const state = (over: Partial<BlendRequestState> = {}): BlendRequestState => ({
  blendClipAPath: '/uploads/a.mp4',
  blendClipBPath: '/uploads/b.mp4',
  blendMode: 'overlap',
  blendOverlapSec: 3,
  blendTransitionSec: 7,
  blendMotionPrefixSec: 1,
  blendMotionSuffixSec: 0.5,
  blendAnchorStrength: 0.8,
  params: { model_type: 'ltx2_22B_distilled_1_1', seed: 4 } as unknown as BlendRequestState['params'],
  activeWorkspace: 'default',
  ...over,
})

test('Insert mode sends the Transition Duration slider, which the server used to never receive', () => {
  const body = buildBlendRequest(state({ blendMode: 'insert' }), '')
  assert.equal(body.blend_mode, 'insert')
  assert.equal(body.transition_sec, 7)
  assert.equal(body.overlap_sec, 3)
})

test('Overlap mode keeps sending the Overlap Duration slider', () => {
  const body = buildBlendRequest(state({ blendMode: 'overlap', blendOverlapSec: 5 }), 'a door opens')
  assert.equal(body.blend_mode, 'overlap')
  assert.equal(body.overlap_sec, 5)
  assert.equal(body.prompt, 'a door opens')
  assert.equal(body.clip_a_path, '/uploads/a.mp4')
  assert.equal(body.motion_prefix_sec, 1)
  assert.equal(body.input_video_strength, 0.8)
})

test('an empty prompt gets the default transition prompt', () => {
  assert.match(buildBlendRequest(state(), '').prompt ?? '', /smooth natural transition/)
})
