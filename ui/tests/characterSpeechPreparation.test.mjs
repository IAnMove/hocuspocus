import assert from 'node:assert/strict'
import test from 'node:test'
import { createCharacterKit } from '../src/lib/characterKit.ts'
import { CHARACTER_MOUTH_STATES } from '../src/lib/characterMouthStates.ts'
import { speechPreparationReadiness } from '../src/lib/characterSpeechPreparation.ts'

const sourceAsset = (id, reviewState = 'approved', source = `${id}.png`, extra = {}) => ({
  id,
  name: id,
  source,
  kind: 'overlay',
  alphaStatus: 'transparent',
  reviewState,
  ...extra,
})

const baseKit = (overrides = {}) => ({
  ...createCharacterKit('Luma'),
  base: sourceAsset('base', 'approved', 'base.png'),
  mouth: {},
  ...overrides,
})

const metadata = (overrides = {}) => ({
  version: 1,
  poseId: 'base',
  poseSource: 'base.png',
  variantSource: 'variant.png',
  sourceWidth: 32,
  sourceHeight: 32,
  region: { x: 12, y: 12, size: 8 },
  feather: .08,
  poseSha256: 'a'.repeat(64),
  variantSha256: 'b'.repeat(64),
  outputSha256: 'c'.repeat(64),
  ...overrides,
})

test('returns all nine mouth rows in fixed order and marks empty sources missing', () => {
  const kit = baseKit({ mouth: {
    closed: sourceAsset('closed'),
    small: sourceAsset('small'),
    wide: sourceAsset('wide', 'approved', ''),
    round: sourceAsset('round', 'rejected', '   '),
  } })

  const readiness = speechPreparationReadiness(kit, 'base')

  assert.deepEqual(readiness.rows, [
    { state: 'closed', status: 'approved' },
    { state: 'small', status: 'approved' },
    { state: 'wide', status: 'missing' },
    { state: 'round', status: 'missing' },
    ...CHARACTER_MOUTH_STATES.slice(4).map(state => ({ state, status: 'missing' })),
  ])
  assert.equal(readiness.poseApproved, true)
  assert.equal(readiness.previewReady, true)
  assert.equal(readiness.complete, false)
})

test('maps pending, rejected and approved assets while requiring a reviewed pose', () => {
  const kit = baseKit({
    base: sourceAsset('base', 'pending', 'base.png'),
    mouth: {
      closed: sourceAsset('closed', 'approved'),
      small: sourceAsset('small', 'pending'),
      wide: sourceAsset('wide', 'rejected'),
      round: sourceAsset('round', 'approved'),
    },
  })

  const readiness = speechPreparationReadiness(kit, '   ')

  assert.equal(readiness.poseApproved, false)
  assert.deepEqual(readiness.rows.slice(0, 4).map(row => row.status), ['approved', 'pending', 'rejected', 'approved'])
  assert.equal(readiness.previewReady, false)
  assert.equal(readiness.complete, false)
})

test('requires a closed state and at least one open state for preview, and all states for completion', () => {
  const mouth = {
    closed: sourceAsset('closed'),
    small: sourceAsset('small', 'pending'),
    wide: sourceAsset('wide', 'pending'),
    round: sourceAsset('round', 'pending'),
  }
  const kit = baseKit({ mouth })

  assert.equal(speechPreparationReadiness(kit, 'base').previewReady, false)

  const oneOpen = speechPreparationReadiness({ ...kit, mouth: { ...mouth, wide: sourceAsset('wide') } }, 'base')
  assert.equal(oneOpen.previewReady, true)
  assert.equal(oneOpen.complete, false)

  const allApproved = speechPreparationReadiness({
    ...kit,
    mouth: {
      closed: sourceAsset('closed'),
      small: sourceAsset('small'),
      wide: sourceAsset('wide'),
      round: sourceAsset('round'),
      ...Object.fromEntries(CHARACTER_MOUTH_STATES.slice(4).map(state => [state, sourceAsset(state)])),
    },
  }, 'base')
  assert.equal(allApproved.previewReady, true)
  assert.equal(allApproved.complete, true)
})

test('marks stale face patches incompatible even when their review state is approved', () => {
  const kit = baseKit({ mouth: {
    closed: sourceAsset('closed', 'approved', 'closed.png', { facePatch: metadata({ poseId: 'side' }) }),
    small: sourceAsset('small', 'approved', 'small.png', { facePatch: metadata({ poseSource: 'old-base.png' }) }),
    wide: sourceAsset('wide'),
    round: sourceAsset('round'),
  } })

  const readiness = speechPreparationReadiness(kit, ' base ')

  assert.deepEqual(readiness.rows, [
    { state: 'closed', status: 'incompatible' },
    { state: 'small', status: 'incompatible' },
    { state: 'wide', status: 'approved' },
    { state: 'round', status: 'approved' },
    ...CHARACTER_MOUTH_STATES.slice(4).map(state => ({ state, status: 'missing' })),
  ])
  assert.equal(readiness.poseApproved, true)
  assert.equal(readiness.previewReady, false)
  assert.equal(readiness.complete, false)
})

test('trims non-base pose ids and defaults blank ids to base', () => {
  const kit = baseKit({
    poses: { side: sourceAsset('side', 'approved', 'side.png') },
    mouth: { closed: sourceAsset('closed'), small: sourceAsset('small') },
  })

  assert.equal(speechPreparationReadiness(kit, '').poseApproved, true)
  assert.equal(speechPreparationReadiness(kit, '  ').poseApproved, true)
  assert.equal(speechPreparationReadiness(kit, ' side ').poseApproved, true)
  assert.equal(speechPreparationReadiness(kit, ' missing ').poseApproved, false)
})

test('a pose with no source is not approved even when its review state is approved', () => {
  const kit = baseKit({
    base: sourceAsset('base', 'approved', ''),
    mouth: { closed: sourceAsset('closed'), wide: sourceAsset('wide') },
  })

  const readiness = speechPreparationReadiness(kit, 'base')

  assert.equal(readiness.poseApproved, false)
  assert.equal(readiness.previewReady, false)
  assert.equal(readiness.complete, false)
})

test('every extended slot must be approved and match the current pose', () => {
  const mouth = Object.fromEntries(CHARACTER_MOUTH_STATES.map(state => [state, sourceAsset(state)]))
  const kit = baseKit({ mouth })
  assert.equal(speechPreparationReadiness(kit, 'base').complete, true)
  for (const state of CHARACTER_MOUTH_STATES.slice(4)) {
    for (const reviewState of ['pending', 'rejected']) {
      const draft = { ...kit, mouth: { ...mouth, [state]: sourceAsset(state, reviewState) } }
      assert.equal(speechPreparationReadiness(draft, 'base').complete, false)
    }
    const missing = { ...kit, mouth: { ...mouth, [state]: undefined } }
    assert.equal(speechPreparationReadiness(missing, 'base').complete, false)
    const stale = { ...kit, mouth: { ...mouth, [state]: sourceAsset(state, 'approved', state + '.png', { facePatch: metadata({ poseSource: 'old.png' }) }) } }
    assert.equal(speechPreparationReadiness(stale, 'base').complete, false)
  }
})
