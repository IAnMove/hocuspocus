import assert from 'node:assert/strict'
import test from 'node:test'
import { estimateSource, kindProgress, produceTargets, specPatch, visibleAssets, waitingSteps } from '../src/features/game-assets/listModel.ts'
import type { GameAsset } from '../src/features/game-assets/types.ts'

function asset(patch: Partial<GameAsset>): GameAsset {
  return {
    id: 'heroe', kind: 'character', name: 'Hero', description: 'knight', status: 'pending', tags: [],
    spec: { role: 'player' }, dependsOn: [], candidates: 1, locked: false, attempts: [], approvedAttemptId: null,
    ...patch,
  }
}

test('filters, produce targets and estimate source stay pure', () => {
  const assets = [
    asset({ id: 'heroe', status: 'review' }),
    asset({ id: 'andar', kind: 'animation', name: 'Walk', status: 'pending', description: 'walk cycle' }),
    asset({ id: 'suelo', kind: 'tile', name: 'Ground', status: 'stale', locked: false }),
    asset({ id: 'cielo', kind: 'tile', name: 'Sky', status: 'stale', locked: true }),
  ]
  assert.deepEqual(visibleAssets(assets, { kind: 'tile', status: '', query: 'sky' }).map(item => item.id), ['cielo'])
  assert.deepEqual(produceTargets(assets, 'pending', []).map(item => item.id), ['andar'])
  assert.deepEqual(produceTargets(assets, 'rerender', []).map(item => item.id), ['suelo'])
  assert.deepEqual(produceTargets(assets, 'selected', ['heroe', 'suelo']).map(item => item.id), ['suelo'])
  assert.equal(estimateSource('history(4)'), 'history')
  assert.equal(estimateSource('trial'), 'trial')
  assert.equal(estimateSource('defaults'), 'defaults')
  const patched = specPatch(assets[1], { name: 'Andar', description: 'cycle', action: 'walk', method: 'strip', frames: '8', fps: '12' })
  assert.equal(patched.name, 'Andar')
  assert.equal((patched.spec as { method: string }).method, 'strip')
  assert.equal((patched.spec as { frames: number }).frames, 8)
})

test('progress counts finished steps and waiting dependencies stay grouped', () => {
  const steps = [
    { assetId: 'a', kind: 'character', status: 'done' },
    { assetId: 'b', kind: 'character', status: 'running' },
    { assetId: 'c', kind: 'animation', status: 'skipped', reason: 'waiting_dependency' },
  ]
  assert.deepEqual(kindProgress(steps), [
    { kind: 'character', done: 1, total: 2 },
    { kind: 'animation', done: 1, total: 1 },
  ])
  assert.deepEqual(waitingSteps(steps).map(step => step.assetId), ['c'])
})
