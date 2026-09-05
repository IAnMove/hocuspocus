import assert from 'node:assert/strict'
import test from 'node:test'

import {
  orderedTimelineShots,
  reconcilePlaybackCursor,
  safeTimelineAttempt,
  seriesEditorCanvas,
} from '../src/lib/orderedClipTimeline.ts'

test('ordered timeline keeps stable shot slots and skips rejected fallback attempts', () => {
  const shots = orderedTimelineShots([
    { id: 'shot-2', order: 2, attempts: [] },
    { id: 'shot-1', order: 1, attempts: [] },
  ])
  assert.deepEqual(shots.map(shot => shot.id), ['shot-1', 'shot-2'])

  const shot = {
    id: 'shot-1', order: 1, attempts: [
      { id: 'good', status: 'completed', outputAssetIds: ['good-video'] },
      { id: 'rejected', status: 'completed', reviewDecision: 'rejected', outputAssetIds: ['bad-video'] },
    ],
  }
  assert.equal(safeTimelineAttempt(shot, () => true)?.id, 'good')
})

test('a completed regeneration replaces the visible slot without erasing the approved fallback', () => {
  const shot = {
    id: 'shot-1', order: 1, approvedAttemptId: 'approved', attempts: [
      { id: 'approved', status: 'completed', outputAssetIds: ['old-video'] },
      { id: 'new', status: 'completed', outputAssetIds: ['new-video'] },
    ],
  }
  assert.equal(safeTimelineAttempt(shot, () => true)?.id, 'new')
})

test('playback cursor follows stable shot identity across reorder and attempt replacement', () => {
  assert.deepEqual(
    reconcilePlaybackCursor('shot-2', [
      { shotId: 'shot-3', attemptId: 'attempt-3' },
      { shotId: 'shot-2', attemptId: 'replacement-attempt' },
      { shotId: 'shot-1', attemptId: 'attempt-1' },
    ]),
    { index: 1, shotId: 'shot-2', outcome: 'keep' },
  )
})

test('playback cursor stops explicitly when its slot disappears or no clips remain', () => {
  assert.deepEqual(
    reconcilePlaybackCursor('shot-2', [{ shotId: 'shot-1' }, { shotId: 'shot-3' }]),
    { index: -1, shotId: null, outcome: 'stop' },
  )
  assert.deepEqual(
    reconcilePlaybackCursor('shot-2', []),
    { index: -1, shotId: null, outcome: 'stop' },
  )
})

test('video editor canvases preserve every native Series tier and orientation', () => {
  assert.deepEqual(seriesEditorCanvas('540p', 'landscape'), {
    label: 'Landscape 540p', width: 960, height: 544,
  })
  assert.deepEqual(seriesEditorCanvas('768p', 'portrait'), {
    label: 'Portrait 768p', width: 768, height: 1344,
  })
})
