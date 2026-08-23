import assert from 'node:assert/strict'
import test from 'node:test'

import { syncTrailerDuration, trailerDurationForProject } from '../src/features/stories/trailerDefaults.ts'

test('untouched trailer defaults follow project type and duration changes', () => {
  assert.equal(trailerDurationForProject('trailer', 90), 90)
  assert.equal(syncTrailerDuration(60, 'trailer', 45, false), 45)
  assert.equal(syncTrailerDuration(45, 'quick_video', 10, false), 15)
  assert.equal(syncTrailerDuration(45, 'music_video', 120, false), 60)
})

test('manual trailer edits survive later project default changes', () => {
  assert.equal(syncTrailerDuration(75, 'trailer', 120, true), 75)
  assert.equal(syncTrailerDuration(75, 'quick_video', 15, true), 75)
})
