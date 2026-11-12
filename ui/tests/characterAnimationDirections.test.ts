import assert from 'node:assert/strict'
import test from 'node:test'
import { contractOf, DIRS, MOTIONS, sheetsFor, walkSheet, WALK_SHEETS } from '../src/lib/characterAnimationDirections.ts'
import type { KitAnimation } from '../src/lib/characterAnimations.ts'

const made = (count: number, extra: Partial<KitAnimation> = {}): KitAnimation => ({
  sheet: { source: '/api/v1/file/s.png?workspace=w', width: 100 * count, height: 640, count, columns: count, rows: 1, cell: { width: 100, height: 640 } },
  frames: [], fps: 4, loop: 'loop', facing: 'right', reviewState: 'approved', ...extra })

// The same cases as tests/test_character_animations.py: the contract is one, in two languages.
test('motion and dir are read from the animation or deduced from its view, group and id', () => {
  assert.deepEqual([...DIRS], ['side', 'front', 'front34', 'back34', 'back'])
  assert.deepEqual([...MOTIONS], ['walk', 'idle'])
  assert.deepEqual(contractOf('walk-front34', { motion: 'walk', dir: 'front34' }), { motion: 'walk', dir: 'front34' })
  assert.deepEqual(contractOf('walk', { view: 'side', group: 'cycle' }), { motion: 'walk', dir: 'side' })
  assert.deepEqual(contractOf('idle', { view: 'front', group: 'cycle' }), { motion: 'idle', dir: 'front' })
  assert.deepEqual(contractOf('walk-back34', { view: 'back34', group: 'cycle' }), { motion: 'walk', dir: 'back34' })
  assert.deepEqual(contractOf('wave', { view: 'front', group: 'gesture' }), { dir: 'front' }, 'a gesture is no motion')
  assert.deepEqual(contractOf('run', { view: 'side', group: 'cycle' }), { dir: 'side' }, 'only walk and idle are motions')
  assert.deepEqual(contractOf('angry', { view: 'bust', group: 'expression' }), {}, 'a bust looks no way')
  assert.deepEqual(contractOf('walk-mine', { view: 'side', group: 'custom' }), { dir: 'side' }, 'a custom id that says walk is not a cycle')
  assert.deepEqual(contractOf('walk-12'), { motion: 'walk', dir: 'side' }, 'a catalog id with no stored entry reads the catalog')
  assert.deepEqual(contractOf('unknown'), {})
  assert.deepEqual(contractOf('walk', { view: 'side', dir: 'back', motion: 'idle' }), { motion: 'idle', dir: 'back' }, 'what is stored wins')
  assert.deepEqual(contractOf('walk', { view: 'side', dir: 'up' as never, motion: 'fly' as never }), { motion: 'walk', dir: 'side' }, 'a value off the list is ignored')
})

test('the approved twelve-pose walk comes before the four-pose one, and a pending or rejected sheet is never played', () => {
  assert.deepEqual([...WALK_SHEETS], ['walk-12', 'walk'])
  const both = { walk: made(4), 'walk-12': made(12) }
  assert.equal(walkSheet(both)?.id, 'walk-12')
  assert.equal(walkSheet({ ...both, 'walk-12': made(12, { reviewState: 'pending' }) })?.id, 'walk')
  assert.equal(walkSheet({ 'walk-12': made(12, { reviewState: 'rejected' }) }), undefined)
  assert.equal(walkSheet({}), undefined)
  assert.equal(walkSheet(undefined), undefined)
  const pool = { 'walk-front34': made(12, { dir: 'front34', motion: 'walk' }), 'walk-back': made(12, { dir: 'back', motion: 'walk' }), walk: made(4) }
  assert.deepEqual(sheetsFor(pool, 'walk', 'front34').map(([id]) => id), ['walk-front34'])
  assert.deepEqual(sheetsFor(pool, 'walk', 'side').map(([id]) => id), ['walk'], 'a walk with no dir stored is a side walk')
  assert.deepEqual(sheetsFor({ ...pool, 'walk-12': made(12) }, 'walk', 'side').map(([id]) => id), ['walk-12', 'walk'], 'more cells first')
  assert.deepEqual(sheetsFor(pool, 'idle', 'side'), [])
})
