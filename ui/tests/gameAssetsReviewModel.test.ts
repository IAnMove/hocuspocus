import assert from 'node:assert/strict'
import test from 'node:test'
import { approvableClean, atlasFrames, countLoop, loopRange, playbackSources, seamTime, stepFrame } from '../src/features/game-assets/reviewModel.ts'
import type { GameAsset, GameAttempt } from '../src/features/game-assets/types.ts'

function attempt(id: string, warnings: string[] = []): GameAttempt {
  return { id, status: 'ok', files: {}, warnings }
}

function asset(id: string, warnings: string[] = [], status = 'review'): GameAsset {
  return {
    id, kind: 'character', name: id, description: '', status, tags: [], spec: {}, dependsOn: [],
    candidates: 1, locked: false, attempts: [attempt(`${id}-a`, warnings)], approvedAttemptId: null,
  }
}

test('atlas frames advance on their duration and then loop', () => {
  const frames = atlasFrames({
    frames: {
      b: { frame: { x: 8, y: 0, w: 8, h: 8 }, duration: 80 },
      a: { frame: { x: 0, y: 0, w: 8, h: 8 }, duration: 80 },
    },
  })
  assert.deepEqual(frames.map(frame => frame.name), ['a', 'b'])
  assert.equal(stepFrame(0, frames.length, true), 1)
  assert.equal(stepFrame(1, frames.length, true), 0)
  assert.equal(stepFrame(1, frames.length, false), 1)
})

test('bulk approve skips assets that carry a warning', () => {
  const picks = approvableClean([asset('clean'), asset('warned', ['loop_seam']), asset('held', [], 'approved')])
  assert.deepEqual(picks, [{ assetId: 'clean', attemptId: 'clean-a' }])
})

test('loop points in samples become seconds and the seam is two seconds before the end', () => {
  const range = loopRange({ loopStart: 0, loopEnd: 144000, duration: 3 })
  assert.equal(range.start, 0)
  assert.equal(range.end, 3)
  assert.equal(seamTime(range.end), 1)
  assert.equal(countLoop(2.9, 0.05, 3, 4), 5)
  assert.equal(countLoop(1, 1.2, 3, 4), 4)
})

test('numbered files are the sfx variants and music prefers ogg', () => {
  assert.deepEqual(playbackSources({ '2': 'b.wav', '1': 'a.wav' }).map(item => item.key), ['1', '2'])
  assert.equal(playbackSources({ wav: 'a.wav', ogg: 'a.ogg' })[0].key, 'ogg')
})
