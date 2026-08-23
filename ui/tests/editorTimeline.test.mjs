import assert from 'node:assert/strict'
import test from 'node:test'
import {
  clipIndexAtTime,
  clipTimelineStart,
  parsePlayheadSeconds,
  sequenceTotalDuration,
  sourceTimeAtSequenceTime,
  transitionTimelineStart,
} from '../src/features/video-editor/editorTimeline.ts'

function clip(overrides = {}) {
  return {
    trimStart: 0,
    trimEnd: 8,
    transition: 'none',
    transitionDuration: 0.5,
    ...overrides,
  }
}

test('hard-cut clips sit end to end on the sequence clock', () => {
  const clips = [clip(), clip({ trimEnd: 6 })]
  assert.equal(clipTimelineStart(clips, 0), 0)
  assert.equal(clipTimelineStart(clips, 1), 8)
  assert.equal(sequenceTotalDuration(clips), 14)
  assert.equal(transitionTimelineStart(clips, 0), 8)
  assert.equal(clipIndexAtTime(clips, 7.99), 0)
  assert.equal(clipIndexAtTime(clips, 8), 1)
  assert.deepEqual(sourceTimeAtSequenceTime(clips, 3), {
    clipIndex: 0, sourceTime: 3, interstitial: false, interstitialElapsed: 0,
  })
})

test('crossfade overlap shortens the sequence and starts the transition before the cut', () => {
  const clips = [clip({ transition: 'crossfade', transitionDuration: 1 }), clip({ trimEnd: 6 })]
  assert.equal(clipTimelineStart(clips, 1), 7)
  assert.equal(transitionTimelineStart(clips, 0), 7)
  assert.equal(sequenceTotalDuration(clips), 13)
})

test('interstitial cards add duration after the outgoing clip', () => {
  const clips = [clip({ transition: 'later-clock', transitionDuration: 2 }), clip({ trimEnd: 4 })]
  assert.equal(clipTimelineStart(clips, 1), 10)
  assert.equal(transitionTimelineStart(clips, 0), 8)
  assert.equal(sequenceTotalDuration(clips), 14)
  const atCard = sourceTimeAtSequenceTime(clips, 9)
  assert.equal(atCard.clipIndex, 0)
  assert.equal(atCard.interstitial, true)
  assert.equal(atCard.interstitialElapsed, 1)
})

test('playhead seconds accept 12, 12.50 and 1:02.25', () => {
  assert.equal(parsePlayheadSeconds('12'), 12)
  assert.equal(parsePlayheadSeconds('12.50'), 12.5)
  assert.equal(parsePlayheadSeconds('1:02.25'), 62.25)
  assert.equal(parsePlayheadSeconds('  7,25 '), 7.25)
  assert.equal(parsePlayheadSeconds('nope'), null)
})
