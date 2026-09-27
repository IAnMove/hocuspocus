import { GENERATION_RECORD_AUTHORITY, type GenerationRecord } from '../../lib/generationRecord.ts'
import { firstText, isTakeStatus, text } from './fields.ts'
import { clipRefs } from './refs.ts'
import { decisionFromTag } from './status.ts'
import {
  attemptsOf,
  extraTakeFromRecord,
  pipelineIsLive,
  previousTakeId,
  restoreSelections,
  selectedTake,
  shotIdOf,
  takeFromAttempt,
} from './takes.ts'
import type { PipelineClipLike, PipelineLike, ReviewDesk, ReviewShot, ReviewTake, TakeRecord } from './types.ts'
import { REVIEW_AUTHORITY } from './types.ts'

export { REVIEW_AUTHORITY }

export function takeRecordFromGeneration(record: GenerationRecord): TakeRecord {
  if (GENERATION_RECORD_AUTHORITY !== 'projection' || REVIEW_AUTHORITY !== 'projection') {
    throw new Error('Review must read generation_record as a projection.')
  }
  return {
    generation_id: record.generation_id,
    production_id: record.production_id,
    cue_id: record.cue_id,
    status: isTakeStatus(record.status) ? record.status : 'planned',
    location: { filename: record.location.filename },
    timestamps: { duration_ms: record.timestamps.duration_ms },
    prompt_full: record.prompt_full,
    lineage: {
      parents: record.lineage.parents.map(item => ({ uri: item.uri, kind: item.kind })),
    },
  }
}

export interface ProjectInput {
  pipeline: PipelineLike
  records?: TakeRecord[]
  productionId?: string
  title?: string
}

export function takesForClip(
  clip: PipelineClipLike,
  records: TakeRecord[],
  productionId: string,
  pipelineLive = false,
): ReviewTake[] {
  const used = new Set<string>()
  const takes = attemptsOf(clip).map(attempt => {
    const take = takeFromAttempt(attempt, records, productionId, clip, pipelineLive)
    if (take.filename) used.add(take.filename)
    return take
  })
  for (const record of records) {
    const extra = extraTakeFromRecord(record, productionId, used, clip)
    if (extra) takes.push(extra)
  }
  return takes
}

export function shotFromClip(
  clip: PipelineClipLike,
  records: TakeRecord[],
  productionId: string,
  pipelineLive = false,
): ReviewShot {
  const takes = takesForClip(clip, records, productionId, pipelineLive)
  const selected = selectedTake(clip, takes)
  const decision = decisionFromTag(clip.tag)
  return {
    id: shotIdOf(clip),
    clipIndex: clip.index,
    durationSeconds: selected?.durationSeconds ?? clip.duration_seconds ?? clip.planned_clip?.duration_sec ?? null,
    notes: text(clip.review_notes),
    decision,
    selectedTakeId: selected?.id || null,
    compareTakeId: previousTakeId(takes, selected?.id),
    approvedTakeId: decision === 'approved' ? selected?.id || null : null,
    takes,
    refs: clipRefs(clip),
    prompt: firstText(clip.video_prompt, clip.image_prompt),
  }
}

export function projectReviewDesk(input: ProjectInput): ReviewDesk {
  const productionId = firstText(input.productionId, input.pipeline.production_id, input.pipeline.pipeline_id)
  const live = pipelineIsLive(input.pipeline.status)
  const records = input.records || []
  const clips = [...input.pipeline.clips].sort((left, right) => left.index - right.index)
  return {
    productionId,
    pipelineId: input.pipeline.pipeline_id,
    workspace: text(input.pipeline.workspace) || 'default',
    title: firstText(input.title, input.pipeline.scene_description, productionId),
    shots: clips.map(clip => shotFromClip(clip, records, productionId, live)),
  }
}

export function refreshReviewDesk(
  current: ReviewDesk,
  pipeline: PipelineLike,
  records: TakeRecord[] = [],
): ReviewDesk {
  return restoreSelections(current, projectReviewDesk({
    pipeline,
    records,
    productionId: current.productionId,
    title: current.title,
  }))
}
