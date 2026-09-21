import assert from 'node:assert/strict'
import test from 'node:test'
import {
  H3_EXPERIMENTAL_MAX_FRAMES,
  h3AlignmentOptions,
  h3MaximumFrames,
  h3WindowMaximumFrames,
  requestedVideoFrames,
  supportsH3ExtendedDuration,
} from '../src/lib/h3ExtendedDuration.ts'

const h3 = { architecture: 'minimax_h3', model_type: 'minimax_h3', frames_maximum: 345, sliding_window_defaults: { window_max: 345 } }

const h3Submit = {
  ...h3,
  fps: 24,
  frames_minimum: 124,
  sliding_window: true,
  frame_alignment_modulus: 17,
  frame_alignment_remainder: 5,
  frame_alignment_mode: 'ceil',
}

function alignFrameCount(
  frames: number,
  options?: {
    frame_alignment_modulus?: number
    frame_alignment_remainder?: number
    frame_alignment_mode?: string
    frames_minimum?: number | null
    frames_maximum?: number | null
  } | null,
): number {
  const modulus = options?.frame_alignment_modulus ?? 0
  if (!modulus || modulus <= 0) return frames
  const remainder = (options?.frame_alignment_remainder ?? 1) % modulus
  const minimum = options?.frames_minimum ?? 1
  const maximum = options?.frames_maximum ?? null
  let n = Math.max(minimum, Math.round(frames))
  if (maximum != null) n = Math.min(maximum, n)
  const delta = ((n - remainder) % modulus + modulus) % modulus
  if (delta) {
    const mode = (options?.frame_alignment_mode ?? 'floor').toLowerCase()
    if (mode === 'ceil') n += modulus - delta
    else if (mode === 'nearest') n += delta >= modulus / 2 ? modulus - delta : -delta
    else n -= delta
  }
  if (maximum != null && n > maximum) n -= modulus
  while (n < minimum) n += modulus
  return n
}

test('30s H3 clips stay opt-in', () => {
  assert.equal(supportsH3ExtendedDuration(h3), true)
  assert.equal(supportsH3ExtendedDuration({ ...h3, audio_only: true }), false)
  assert.equal(supportsH3ExtendedDuration({ ...h3, model_type: 'viggle_animate' }), false)
  assert.equal(h3MaximumFrames(h3, false), 345)
  assert.equal(h3MaximumFrames(h3, true), H3_EXPERIMENTAL_MAX_FRAMES)
  assert.equal(h3WindowMaximumFrames(h3, true), H3_EXPERIMENTAL_MAX_FRAMES)
  assert.equal(h3WindowMaximumFrames(h3, false), 345)
})

test('30s H3 submit does not inherit the catalog 15s ceiling', () => {
  assert.equal(h3AlignmentOptions(h3Submit, true)?.frames_maximum, H3_EXPERIMENTAL_MAX_FRAMES)
  assert.equal(h3AlignmentOptions(h3Submit, false)?.frames_maximum, 345)
  assert.equal(h3Submit.frames_maximum, 345)
  assert.equal(alignFrameCount(720, h3Submit), 345)
  assert.equal(alignFrameCount(720, h3AlignmentOptions(h3Submit, true)), H3_EXPERIMENTAL_MAX_FRAMES)
  assert.equal(requestedVideoFrames(30, h3Submit, false, alignFrameCount), 345)
  assert.equal(requestedVideoFrames(30, h3Submit, true, alignFrameCount), H3_EXPERIMENTAL_MAX_FRAMES)
  assert.equal(requestedVideoFrames(5, h3Submit, true, alignFrameCount), 124)
})
