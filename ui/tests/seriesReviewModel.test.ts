import assert from 'node:assert/strict'
import test from 'node:test'
import {
  classifyShot, draftNote, episodeReview, filterStatus, groupShotsByScene, latestTakeMedia, noteStage, reviewStage, reviewSummary,
  shotCast, shotDressing, shotReview,
} from '../src/features/series/reviewModel'
import type { SeriesShotReview } from '../src/features/series/types'
import { episode, series, shot, take } from './seriesReviewFixtures'

const entry = (patch: Partial<SeriesShotReview> = {}): SeriesShotReview => ({ plan: 'pending', preview: 'pending', notes: [], ...patch })

test('an episode without a review is direct with every shot pending and no notes', () => {
  const ep = episode([shot('s1', 1)])
  assert.deepEqual(episodeReview(ep), { mode: 'direct', updatedAt: undefined, shots: {} })
  assert.deepEqual(shotReview(ep, 's1'), { plan: 'pending', preview: 'pending', notes: [] })
  const bad = episode([shot('s1', 1)], { mode: 'sideways' as never, shots: { s1: { plan: 'maybe', preview: 'approved' } as never } })
  assert.equal(episodeReview(bad).mode, 'direct')
  assert.equal(shotReview(bad, 's1').plan, 'pending')
  assert.equal(shotReview(bad, 's1').preview, 'approved')
})

test('direct and plan modes: ready needs an approved completed take; plan mode waits for the plan first', () => {
  const rendered = shot('s1', 1, { attempts: [take('a1')], approvedAttemptId: 'a1' })
  const fresh = shot('s2', 2)
  assert.equal(classifyShot(rendered, entry(), 'direct'), 'ready')
  assert.equal(classifyShot(fresh, entry(), 'direct'), 'render')
  assert.equal(classifyShot(rendered, entry(), 'plan'), 'approve_plan')
  assert.equal(classifyShot(fresh, entry({ plan: 'changes' }), 'plan'), 'changes')
  assert.equal(classifyShot(fresh, entry({ plan: 'approved' }), 'plan'), 'render')
  assert.equal(classifyShot(rendered, entry({ plan: 'approved' }), 'plan'), 'ready')
})

test('preview mode walks plan -> preview -> review -> final', () => {
  const none = shot('s1', 1)
  const preview = shot('s1', 1, { attempts: [take('p1', { reviewStage: 'preview' })] })
  assert.equal(classifyShot(none, entry(), 'preview'), 'approve_plan')
  assert.equal(classifyShot(none, entry({ plan: 'approved' }), 'preview'), 'render_previews')
  assert.equal(classifyShot(preview, entry({ plan: 'approved' }), 'preview'), 'approve_previews')
  assert.equal(classifyShot(preview, entry({ plan: 'approved', preview: 'changes' }), 'preview'), 'changes')
  // Approved 2D preview not yet the approved take: the server promotes it.
  assert.equal(classifyShot(preview, entry({ plan: 'approved', preview: 'approved', previewAttemptId: 'p1' }), 'preview'), 'render_final')
  const promoted = { ...preview, approvedAttemptId: 'p1' }
  assert.equal(classifyShot(promoted, entry({ plan: 'approved', preview: 'approved', previewAttemptId: 'p1' }), 'preview'), 'ready')
})

test('a 3D preview at draft quality is not the final of a shot rendered at final quality', () => {
  const scene3d = { template: 'user-moon', quality: 'final' as const }
  const reviewed = entry({ plan: 'approved', preview: 'approved', previewAttemptId: 'p1' })
  const draft = shot('s1', 1, { productionMethod: 'animation_3d', scene3d, attempts: [take('p1', { reviewStage: 'preview' })], approvedAttemptId: 'p1' })
  assert.equal(classifyShot(draft, reviewed, 'preview'), 'render_final')
  const final = { ...draft, attempts: [...draft.attempts, take('f1', { reviewStage: 'final' })], approvedAttemptId: 'f1' }
  assert.equal(classifyShot(final, reviewed, 'preview'), 'ready')
  // A final made before the reviewed preview does not count.
  const stale = { ...draft, attempts: [take('f0', { reviewStage: 'final' }), take('p1', { reviewStage: 'preview' })], approvedAttemptId: 'f0' }
  assert.equal(classifyShot(stale, reviewed, 'preview'), 'render_final')
  const draftQuality = { ...draft, scene3d: { template: 'user-moon', quality: 'draft' as const } }
  assert.equal(classifyShot(draftQuality, reviewed, 'preview'), 'ready')
})

test('summary counts, orders the steps and names the next action', () => {
  const ep = episode([
    shot('s1', 1), shot('s2', 2), shot('s3', 3, { attempts: [take('a3')] }), shot('s4', 4),
  ], { mode: 'preview', shots: {
    s2: entry({ plan: 'changes' }), s3: entry({ plan: 'approved' }), s4: entry({ plan: 'approved' }),
  } })
  const summary = reviewSummary(ep)
  assert.deepEqual(summary.plan, { pending: 1, approved: 2, changes: 1 })
  assert.deepEqual(summary.steps, [
    { kind: 'changes', count: 1 }, { kind: 'approve_plan', count: 1 }, { kind: 'render_previews', count: 1 }, { kind: 'approve_previews', count: 1 },
  ])
  assert.deepEqual(summary.nextStep, { kind: 'approve_plan', count: 1 })
  assert.deepEqual(summary.filters, { all: 4, pending: 3, changes: 1, approved: 0 })
  const done = episode([shot('s1', 1, { attempts: [take('a1')], approvedAttemptId: 'a1' })])
  assert.deepEqual(reviewSummary(done).nextStep, { kind: 'assemble', count: 1 })
  const onlyChanges = episode([shot('s1', 1)], { mode: 'plan', shots: { s1: entry({ plan: 'changes' }) } })
  assert.deepEqual(reviewSummary(onlyChanges).nextStep, { kind: 'changes', count: 1 })
})

test('filters: approved means the review the mode asks for has passed; changes wins over pending', () => {
  const rendered = shot('s1', 1, { attempts: [take('a1')] })
  assert.equal(filterStatus(rendered, entry({ plan: 'approved' }), 'plan'), 'approved')
  assert.equal(filterStatus(rendered, entry({ plan: 'approved' }), 'preview'), 'pending')
  assert.equal(filterStatus(rendered, entry({ plan: 'approved', preview: 'approved' }), 'preview'), 'approved')
  assert.equal(filterStatus(rendered, entry({ plan: 'approved', preview: 'changes' }), 'preview'), 'changes')
  assert.equal(filterStatus(rendered, entry({ preview: 'approved' }), 'direct'), 'approved')
  assert.equal(filterStatus(shot('s2', 2), entry({ plan: 'approved' }), 'direct'), 'approved')
})

test('the buttons act on the plan until it is approved, then on the preview; notes follow the server default', () => {
  const rendered = shot('s1', 1, { attempts: [take('a1')] })
  assert.equal(reviewStage('preview', entry(), rendered), 'plan')
  assert.equal(reviewStage('preview', entry({ plan: 'approved' }), rendered), 'preview')
  assert.equal(reviewStage('plan', entry({ plan: 'approved' }), rendered), 'plan')
  assert.equal(reviewStage('direct', entry(), rendered), 'preview')
  assert.equal(reviewStage('direct', entry(), shot('s2', 2)), 'plan')
  assert.equal(noteStage('direct', entry()), 'final')
  assert.equal(noteStage('plan', entry({ plan: 'approved' })), 'plan')
  assert.equal(noteStage('preview', entry()), 'plan')
  assert.equal(noteStage('preview', entry({ plan: 'approved' })), 'preview')
})

test('the notes box keeps editing the user\'s last note at the stage until an agent answers', () => {
  const note = (id: string, by: 'user' | 'agent', stage: 'plan' | 'preview' = 'plan') => ({ id, at: '2026-10-06T10:00:00Z', stage, text: id, by })
  assert.equal(draftNote(entry({ notes: [note('n1', 'user'), note('n2', 'user', 'preview')] }), 'plan')?.id, 'n1')
  assert.equal(draftNote(entry({ notes: [note('n1', 'user'), note('n2', 'agent')] }), 'plan'), undefined)
})

test('shots are grouped by scene in script order; an unknown scene goes last', () => {
  const ep = episode([shot('s3', 3, { sceneId: 'scene-2' }), shot('s1', 1), shot('s2', 2), shot('s4', 4, { sceneId: 'ghost' })])
  const groups = groupShotsByScene(ep)
  assert.deepEqual(groups.map(group => [group.sceneId, group.number, group.shots.map(item => item.id)]),
    [['scene-1', 1, ['s1', 's2']], ['scene-2', 2, ['s3']], ['ghost', 3, ['s4']]])
  assert.equal(groups[0].locationId, 'nave')
})

test('card helpers: cast with poses, dressing and the latest take\'s video and scene', () => {
  const planned = shot('s1', 1, {
    layout2d: { cast: [{ characterId: 'ines', poseId: 'busto', x: 40 }], fx: [{ kind: 'vignette' }, { kind: 'candlelight' }, { kind: 'vignette' }],
      sfx: [{ file: 'door.wav' }], card: { kind: 'title' }, music: { file: 'theme.wav' } },
    attempts: [take('a1'), take('a2', { reviewDecision: 'rejected' })],
  })
  const project = series(episode([planned]))
  assert.deepEqual(shotCast(project, planned), [{ characterId: 'ines', poseId: 'busto', x: 40, name: 'Capitana Inés Valdés' }])
  assert.deepEqual(shotCast(project, shot('s2', 2)), [{ characterId: 'ines', name: 'Capitana Inés Valdés' }])
  assert.deepEqual(shotDressing(planned).map(item => item.key), ['fx', 'sfx', 'cardKind', 'music'])
  assert.equal(shotDressing(planned)[0].values.list, 'vignette, candlelight')
  const media = latestTakeMedia(project, planned)
  assert.equal(media?.attempt.id, 'a1')
  assert.equal(media?.sceneFilename, 'mp-es-ep1-s1.scene.json')
  assert.match(media?.url || '', /\/api\/v1\/file\/assets%2Fmp-es%2Fasset-a1\.mp4\?workspace=plus-ultra$/)
  assert.match(media?.thumbnail || '', /\/api\/v1\/outputs\/thumbnail\//)
  const scene3d = shot('s3', 3, { productionMethod: 'animation_3d', scene3d: { template: 'user-moon', objects: [{}, {}], quality: 'final' } })
  assert.deepEqual(shotDressing(scene3d), [{ key: 'scene3d', values: { source: 'user-moon', objects: 2, quality: 'final' } }])
})
