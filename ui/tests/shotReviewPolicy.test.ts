import assert from 'node:assert/strict'
import test from 'node:test'

import { bulkApproveSelections, explicitAttemptSelection, missingAssemblyShotOrders } from '../src/features/series/shotReviewPolicy.ts'

const assets = new Set(['ok-a', 'ok-b', 'ok-new'])
const hasAsset = (id: string) => assets.has(id)

test('bulk approve fills pending shots and keeps an existing final', () => {
  const shots = [
    {
      id: 'shot-1',
      approvedAttemptId: 'chosen',
      attempts: [
        { id: 'chosen', status: 'completed', outputAssetIds: ['ok-a'] },
        { id: 'newer', status: 'completed', outputAssetIds: ['ok-new'] },
      ],
    },
    {
      id: 'shot-2',
      attempts: [
        { id: 'latest', status: 'completed', outputAssetIds: ['ok-b'] },
      ],
    },
    {
      id: 'shot-3',
      attempts: [
        { id: 'failed', status: 'failed', outputAssetIds: [] },
      ],
    },
  ]
  const pending = bulkApproveSelections(shots, hasAsset, { replaceFinals: false })
  assert.deepEqual(pending.selections, [{ shotId: 'shot-2', attemptId: 'latest' }])
  assert.equal(pending.kept, 1)
  assert.equal(pending.omitted, 1)
  assert.equal(pending.replaced, 0)

  const replace = bulkApproveSelections(shots, hasAsset, { replaceFinals: true })
  assert.deepEqual(replace.selections, [
    { shotId: 'shot-1', attemptId: 'newer' },
    { shotId: 'shot-2', attemptId: 'latest' },
  ])
  assert.equal(replace.replaced, 1)
})

test('assembly lists missing shot orders and does not treat incomplete takes as ready', () => {
  const shots = [
    {
      order: 1,
      approvedAttemptId: 'ok',
      attempts: [{ id: 'ok', status: 'completed', outputAssetIds: ['ok-a'] }],
    },
    {
      order: 2,
      approvedAttemptId: 'broken',
      attempts: [{ id: 'broken', status: 'completed', outputAssetIds: ['missing'] }],
    },
    {
      order: 3,
      attempts: [{ id: 'latest', status: 'completed', outputAssetIds: ['ok-b'] }],
    },
  ]
  assert.deepEqual(missingAssemblyShotOrders(shots, hasAsset), [2, 3])
})

test('explicit later attempt can still replace a final when replaceFinals is set', () => {
  const shots = [{
    id: 'shot-1',
    approvedAttemptId: 'chosen',
    attempts: [
      { id: 'chosen', status: 'completed', outputAssetIds: ['ok-a'] },
      { id: 'newer', status: 'completed', outputAssetIds: ['ok-new'] },
    ],
  }]
  const result = bulkApproveSelections(shots, hasAsset, { replaceFinals: true })
  assert.deepEqual(result.selections, [{ shotId: 'shot-1', attemptId: 'newer' }])
})

test('a concrete attemptId selects that historical take, not the latest take of shot 2', () => {
  const shot2 = {
    id: 'shot-2',
    order: 2,
    attempts: [
      { id: 'take-1', status: 'completed', outputAssetIds: ['ok-a'] },
      { id: 'take-2', status: 'completed', outputAssetIds: ['ok-b'] },
    ],
  }
  const latest = bulkApproveSelections([shot2], hasAsset, { replaceFinals: true })
  assert.deepEqual(latest.selections, [{ shotId: 'shot-2', attemptId: 'take-2' }])
  assert.deepEqual(
    explicitAttemptSelection([shot2], 'take-1', hasAsset),
    [{ shotId: 'shot-2', attemptId: 'take-1' }],
  )
  assert.throws(
    () => explicitAttemptSelection([shot2, { id: 'shot-1', attempts: shot2.attempts }], 'take-1', hasAsset),
    /exactly one shot/,
  )
  assert.throws(
    () => explicitAttemptSelection([shot2], 'take-missing', hasAsset),
    /does not belong to shot 2/,
  )
})
