import assert from 'node:assert/strict'
import test from 'node:test'
import {
  H3_EXPERIMENTAL_MAX_FRAMES,
  h3MaximumFrames,
  h3WindowMaximumFrames,
  supportsH3ExtendedDuration,
} from '../src/lib/h3ExtendedDuration.ts'

const h3 = { architecture: 'minimax_h3', model_type: 'minimax_h3', frames_maximum: 345, sliding_window_defaults: { window_max: 345 } }

test('30s H3 clips stay opt-in', () => {
  assert.equal(supportsH3ExtendedDuration(h3), true)
  assert.equal(supportsH3ExtendedDuration({ ...h3, audio_only: true }), false)
  assert.equal(supportsH3ExtendedDuration({ ...h3, model_type: 'viggle_animate' }), false)
  assert.equal(h3MaximumFrames(h3, false), 345)
  assert.equal(h3MaximumFrames(h3, true), H3_EXPERIMENTAL_MAX_FRAMES)
  assert.equal(h3WindowMaximumFrames(h3, true), H3_EXPERIMENTAL_MAX_FRAMES)
  assert.equal(h3WindowMaximumFrames(h3, false), 345)
})
