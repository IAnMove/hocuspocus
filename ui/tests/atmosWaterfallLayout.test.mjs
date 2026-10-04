import assert from 'node:assert/strict'
import test from 'node:test'
import { CLEARING_SUBJECT } from '../src/features/scene3d/atmos/layout.ts'
import { cliffBoulders, poolRocks, rimPines, FALLS_X, POOL, SHEET_Z } from '../src/features/scene3d/atmos/sets/waterfallLayout.ts'

test('waterfall rock is deterministic and leaves the water sheet clear', () => {
  const seed = 24011
  assert.deepEqual(cliffBoulders(seed), cliffBoulders(seed))
  const boulders = cliffBoulders(seed)
  assert.ok(boulders.length >= 250)
  for (const rock of boulders) {
    if (Math.abs(rock.x - FALLS_X) > 1.1 || rock.y > 5.3) continue
    assert.ok(rock.z + rock.sz * 1.05 <= SHEET_Z + 0.15, `rock at ${rock.x.toFixed(2)},${rock.y.toFixed(2)},${rock.z.toFixed(2)} crosses the sheet`)
  }
})

test('the pool and its rocks stay clear of the subject', () => {
  const near = (x, z, r) => (x - CLEARING_SUBJECT[0]) ** 2 + (z - CLEARING_SUBJECT[2]) ** 2 < r * r
  const edge = Math.hypot((CLEARING_SUBJECT[0] - POOL.x) / POOL.rx, (CLEARING_SUBJECT[2] - POOL.z) / POOL.rz)
  assert.ok(edge > 1.3)
  for (const rock of poolRocks(24011)) assert.equal(near(rock.x, rock.z, 0.9), false)
  for (const pine of rimPines(24011)) assert.equal(near(pine.x, pine.z, 1.4), false)
})
