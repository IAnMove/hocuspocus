import assert from 'node:assert/strict'
import { test } from 'node:test'
import { boltChannels, strikeState, strikeTimes, strokeTimes } from '../src/features/sceneFx/lightningBolt'

test('a bolt keeps its shape for a whole strike and changes between strikes', () => {
  assert.deepEqual(boltChannels(42), boltChannels(42))
  assert.notDeepEqual(boltChannels(42)[0].points, boltChannels(43)[0].points)
  const [main, ...branches] = boltChannels(42)
  assert.deepEqual(main.points[0], [0, 0, 0])
  assert.equal(main.points.at(-1)![1], 1, 'the main channel reaches the strike point')
  assert.ok(branches.length >= 7 && branches.every(branch => branch.width < main.width))
  assert.ok(branches.every(branch => branch.order[0] > 0 && branch.order[0] < 1), 'branches light up after the leader passes them')
})

test('a strike creeps down as a leader, flashes, flickers and goes dark', () => {
  const span = 6
  assert.ok(strikeState(7, .02, span).leader < 1)
  assert.ok(strikeState(7, .02, span).brightness < strikeState(7, .08, span).brightness)
  assert.equal(strikeState(7, .08, span).leader, 1)
  const [, second] = strikeTimes(7, span)
  assert.ok(second > .5, 're-strikes leave a dark gap')
  assert.equal(strikeState(7, Math.min(1.2, second - .01), span).brightness > .05, false)
  assert.ok(strikeState(7, second + .08, span).strike === 1)
  assert.ok(strikeState(7, span - .001, span).brightness < .05, 'fades out with the cue')
})

test('thunder cracks land on the return strokes the picture shows', () => {
  const span = 8
  for (const at of strokeTimes(11, span)) {
    const state = strikeState(11, at + .005, span)
    assert.equal(state.leader, 1); assert.ok(state.brightness > 1)
  }
})
