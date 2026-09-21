import assert from 'node:assert/strict'
import test from 'node:test'
import { projectFromAssetManifest } from '../src/lib/generationRecord.ts'
import {
  applyPersistCommands,
  applyRegenPlan,
  approveShot,
  assertRecordProjection,
  canApproveTake,
  exportApprovedSelection,
  isSameProduction,
  isTakeCompleted,
  isTakeQueued,
  localeKeyParity,
  openReviewFromActivity,
  persistCommandsFor,
  planSubsetRegeneration,
  productionIdFromActivity,
  projectReviewDesk,
  queuedTakeFromJob,
  refreshReviewDesk,
  rejectShot,
  selectExactTake,
  setShotNotes,
  takeRecordFromGeneration,
} from '../src/features/production-review/index.ts'
import type { AttemptLike, PipelineClipLike, PipelineLike, TakeRecord, TakeStatus } from '../src/features/production-review/types.ts'

function attempt(filename: string): AttemptLike {
  return { id: filename, filename, created_at: 1 }
}

function record(id: string, filename: string, status: TakeStatus = 'completed', extras: Partial<TakeRecord> = {}): TakeRecord {
  return {
    generation_id: id,
    production_id: 'prod-1',
    status,
    location: { filename },
    timestamps: { duration_ms: 4000 },
    prompt_full: `prompt ${id}`,
    ...extras,
  }
}

function clip(index: number, files: string[], selected: string, extras: Partial<PipelineClipLike> = {}): PipelineClipLike {
  return {
    index,
    shot_id: `shot-${index + 1}`,
    duration_seconds: 4,
    video_filename: selected,
    selected_video_filename: selected,
    video_attempts: files.map(attempt),
    h3_references: { image_references: [`hero-${index + 1}.png`], shot_frame: `frame-${index + 1}.png` },
    start_image_filename: `start-${index + 1}.png`,
    video_prompt: `prompt ${index + 1}`,
    ...extras,
  }
}

function pipelineWith(clips: PipelineClipLike[], status = 'completed'): PipelineLike {
  return {
    pipeline_id: 'pipe-1',
    production_id: 'prod-1',
    workspace: 'film',
    scene_description: 'Night watch',
    status,
    clips,
  }
}

function tenPack() {
  const clips = Array.from({ length: 10 }, (_, index) => (
    clip(index, [`s${index + 1}a.mp4`, `s${index + 1}b.mp4`], `s${index + 1}b.mp4`)
  ))
  const records = Array.from({ length: 10 }, (_, index) => [
    record(`gen-${index + 1}a`, `s${index + 1}a.mp4`),
    record(`gen-${index + 1}b`, `s${index + 1}b.mp4`),
  ]).flat()
  return { pipeline: pipelineWith(clips), records }
}

test('english and spanish review catalogs expose the same keys', () => {
  assert.deepEqual(localeKeyParity(), [])
})

test('selecting an older attempt keeps that generation id after persist and refresh', () => {
  const { pipeline, records } = tenPack()
  let desk = projectReviewDesk({ pipeline, records, productionId: 'prod-1' })
  assert.equal(desk.shots[0].selectedTakeId, 'gen-1b')
  desk = selectExactTake(desk, 'shot-1', 'gen-1a')
  assert.equal(desk.shots[0].selectedTakeId, 'gen-1a')
  const saved = applyPersistCommands(pipeline, persistCommandsFor(desk))
  assert.equal(saved.clips[0].selected_video_filename, 's1a.mp4')
  const refreshed = refreshReviewDesk(desk, saved, records)
  assert.equal(refreshed.shots[0].selectedTakeId, 'gen-1a')
  assert.equal(refreshed.productionId, 'prod-1')
})

test('regenerating 2 of 10 preserves the other eight and notes if one fails', () => {
  const { pipeline, records } = tenPack()
  const desk = projectReviewDesk({ pipeline, records })
  const snapshot = desk.shots.slice(2).map(shot => ({
    id: shot.id, selectedTakeId: shot.selectedTakeId, notes: shot.notes, takeIds: shot.takes.map(take => take.id).join(','),
  }))
  assert.throws(() => planSubsetRegeneration(desk, ['shot-1', 'shot-2'], { confirm: false }))
  const plan = planSubsetRegeneration(desk, ['shot-1', 'shot-2'], { confirm: true })
  assert.equal(plan.jobs.length, 2)
  assert.equal(plan.keepShotIds.length, 8)
  assert.deepEqual(plan.jobs[0].refs.sort(), ['hero-1.png', 'frame-1.png', 'start-1.png'].sort())
  const next = applyRegenPlan(desk, plan, [
    { shotId: 'shot-1', ok: true, take: queuedTakeFromJob(plan.jobs[0], 'gen-1c') },
    { shotId: 'shot-2', ok: false, error: 'provider timeout' },
  ])
  assert.equal(next.shots[0].takes.some(take => take.id === 'gen-1c'), true)
  assert.equal(next.shots[0].takes.find(take => take.id === 'gen-1c')?.refs.includes('hero-1.png'), true)
  assert.match(next.shots[1].notes, /provider timeout/)
  assert.deepEqual(next.shots.slice(2).map(shot => ({
    id: shot.id, selectedTakeId: shot.selectedTakeId, notes: shot.notes, takeIds: shot.takes.map(take => take.id).join(','),
  })), snapshot)
})

test('approved clips are kept when a subset regenerate is requested', () => {
  const { pipeline, records } = tenPack()
  let desk = projectReviewDesk({ pipeline, records })
  desk = approveShot(desk, 'shot-1', 'gen-1b')
  const plan = planSubsetRegeneration(desk, ['shot-1', 'shot-2'], { confirm: true })
  assert.deepEqual(plan.jobs.map(job => job.shotId), ['shot-2'])
  assert.equal(plan.keepShotIds.includes('shot-1'), true)
})

test('export uses the approved selection only and skips queued takes', () => {
  const { pipeline, records } = tenPack()
  records.push(record('gen-queued', 's1q.mp4', 'queued'))
  pipeline.clips[0].video_attempts?.push(attempt('s1q.mp4'))
  let desk = projectReviewDesk({ pipeline, records })
  desk = approveShot(desk, 'shot-1', 'gen-1b')
  desk = approveShot(desk, 'shot-3', 'gen-3b')
  desk = selectExactTake(desk, 'shot-1', 'gen-queued')
  const queued = desk.shots[0].takes.find(take => take.id === 'gen-queued')
  assert.equal(isTakeQueued(queued!), true)
  assert.equal(isTakeCompleted(queued!), false)
  assert.equal(canApproveTake(queued), false)
  assert.throws(() => approveShot(desk, 'shot-1', 'gen-queued'))
  const exported = exportApprovedSelection(desk)
  assert.deepEqual(exported.clips.map(item => item.takeId), ['gen-3b'])
  assert.equal(exported.clips.some(item => item.takeId === 'gen-queued'), false)
  assert.equal(desk.shots[0].approvedTakeId, null)
  assert.equal(exported.omitted.some(item => item.shotId === 'shot-1' && item.reason === 'not_approved'), true)
  assert.equal(exported.omitted.filter(item => item.reason === 'not_approved').length >= 8, true)
})

test('Activity opens the same production by production or pipeline id', () => {
  const { pipeline, records } = tenPack()
  const desk = projectReviewDesk({ pipeline, records })
  const fromEntity = productionIdFromActivity({
    kind: 'production',
    id: 'story-1',
    metadata: { entity_type: 'production', entity_id: 'prod-1', project_id: 'story-1', pipeline_id: 'pipe-1' },
  })
  assert.equal(fromEntity, 'prod-1')
  const opened = openReviewFromActivity(desk, {
    project: { kind: 'director_production', id: 'prod-1' },
    primary: { pipeline_id: 'pipe-1', metadata: { production_id: 'prod-1' } },
  })
  assert.equal(opened?.same, true)
  assert.equal(isSameProduction(desk, { kind: 'pipeline', id: 'pipe-1' }), true)
  assert.equal(isSameProduction(desk, { kind: 'story', id: 'other' }), false)
})

test('review notes round-trip through pipeline state without rewriting generation ids', () => {
  const { pipeline, records } = tenPack()
  let desk = projectReviewDesk({ pipeline, records })
  desk = setShotNotes(desk, 'shot-4', 'hold the lantern lower')
  desk = rejectShot(desk, 'shot-4', 'gen-4b')
  const saved = applyPersistCommands(pipeline, persistCommandsFor(desk))
  assert.equal(saved.clips[3].review_notes, 'hold the lantern lower')
  assert.equal(saved.clips[3].tag, 'needs_work')
  const refreshed = refreshReviewDesk(desk, saved, records)
  assert.equal(refreshed.shots[3].notes, 'hold the lantern lower')
  assert.equal(refreshed.shots[3].decision, 'rejected')
  assertRecordProjection(records[0], {})
  assert.throws(() => assertRecordProjection(records[0], { generation_id: 'other' }))
})

test('generation records stay on their own shot and do not overwrite an empty clip', () => {
  const { pipeline, records } = tenPack()
  pipeline.clips.push({
    index: 10,
    shot_id: 'shot-11',
    video_filename: null,
    selected_video_filename: null,
    video_attempts: [],
    video_prompt: 'pending lantern',
  })
  records.push(record('gen-orphan-11', 's11-only.mp4', 'completed', { clip_index: 10, shot_id: 'shot-11' }))
  const desk = projectReviewDesk({ pipeline, records, productionId: 'prod-1' })
  assert.deepEqual(desk.shots[0].takes.map(take => take.id).sort(), ['gen-1a', 'gen-1b'])
  assert.equal(desk.shots[0].takes.some(take => take.id.startsWith('gen-2')), false)
  assert.equal(desk.shots[10].selectedTakeId, 'gen-orphan-11')
  assert.deepEqual(desk.shots[10].takes.map(take => take.id), ['gen-orphan-11'])
  const noted = persistCommandsFor(setShotNotes(desk, 'shot-1', 'keep the lantern'), ['shot-1'])
  const saved = applyPersistCommands(pipeline, noted)
  assert.equal(saved.clips[0].review_notes, 'keep the lantern')
  assert.equal(saved.clips[10].video_filename, null)
  assert.equal(saved.clips[10].selected_video_filename, null)
  assert.equal(noted.every(command => command.clipIndex === 0), true)
})

test('re-persisting the current take does not clear a stale clip', () => {
  const { pipeline, records } = tenPack()
  pipeline.clips[1].video_stale = true
  const desk = projectReviewDesk({ pipeline, records })
  const saved = applyPersistCommands(pipeline, persistCommandsFor(desk, ['shot-2']))
  assert.equal(saved.clips[1].video_stale, true)
  assert.equal(saved.clips[1].selected_video_filename, 's2b.mp4')
  const moved = applyPersistCommands(pipeline, persistCommandsFor(selectExactTake(desk, 'shot-2', 'gen-2a'), ['shot-2']))
  assert.equal(moved.clips[1].selected_video_filename, 's2a.mp4')
  assert.equal(moved.clips[1].video_stale, false)
})

test('notes persist restates an existing stale approval instead of omitting the tag', () => {
  const { pipeline, records } = tenPack()
  pipeline.clips[0].tag = 'good'
  pipeline.clips[0].video_stale = true
  const desk = setShotNotes(projectReviewDesk({ pipeline, records }), 'shot-1', 'rerun the start frame')
  const commands = persistCommandsFor(desk, ['shot-1'])
  assert.equal(commands.find(command => command.type === 'tag_clip')?.tag, 'good')
  assert.equal(commands.find(command => command.type === 'note_clip')?.notes, 'rerun the start frame')
  const saved = applyPersistCommands(pipeline, commands)
  assert.equal(saved.clips[0].tag, 'good')
  assert.equal(saved.clips[0].review_notes, 'rerun the start frame')
  assert.equal(saved.clips[0].video_stale, true)
})

test('generation records are read as a projection including queued status and duration', () => {
  const generated = takeRecordFromGeneration(projectFromAssetManifest({
    asset: { id: 'asset_clip', filename: 's1a.mp4' },
    origin: { tool: 'director', production: { kind: 'production', id: 'prod-1' }, output_folder: 'film' },
    execution: { status: 'queued', job_id: 'job-1' },
    generation: { prompts: { effective: 'lantern walk' } },
    timing: { total_ms: 5500 },
    technical: { generation_id: 'gen-1a' },
  }))
  assert.equal(generated.generation_id, 'gen-1a')
  assert.equal(generated.status, 'queued')
  assert.equal(generated.timestamps?.duration_ms, 5500)
  const pipeline = pipelineWith([clip(0, ['s1a.mp4'], 's1a.mp4')], 'running')
  const desk = projectReviewDesk({ pipeline, records: [generated] })
  assert.equal(isTakeCompleted(desk.shots[0].takes[0]), false)
  assert.equal(desk.shots[0].takes[0].durationSeconds, 5.5)
})
