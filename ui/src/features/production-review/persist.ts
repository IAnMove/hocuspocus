import { filenameOf } from './fields.ts'
import { REVIEW_AUTHORITY } from './types.ts'
import type { PersistCommand, PipelineClipLike, PipelineLike, TakeRecord } from './types.ts'

export { REVIEW_AUTHORITY }

function clipAt(pipeline: PipelineLike, index: number): PipelineClipLike {
  const clip = pipeline.clips.find(item => item.index === index) || pipeline.clips[index]
  if (!clip) throw new Error(`Clip ${index} is not in pipeline ${pipeline.pipeline_id}.`)
  return clip
}

function withClip(pipeline: PipelineLike, index: number, patch: Partial<PipelineClipLike>): PipelineLike {
  return {
    ...pipeline,
    clips: pipeline.clips.map(clip => clip.index === index ? { ...clip, ...patch } : clip),
  }
}

function applySelect(pipeline: PipelineLike, command: Extract<PersistCommand, { type: 'select_take' }>): PipelineLike {
  const clip = clipAt(pipeline, command.clipIndex)
  const attempts = [...(clip.video_attempts || [])]
  if (!attempts.some(item => item.filename === command.filename)) {
    attempts.push({ id: command.takeId, filename: command.filename, source: 'regenerated' })
  }
  const alreadySelected = filenameOf(clip.selected_video_filename || clip.video_filename) === command.filename
  return withClip(pipeline, command.clipIndex, {
    selected_video_filename: command.filename,
    video_filename: command.filename,
    video_stale: alreadySelected ? Boolean(clip.video_stale) : false,
    video_attempts: attempts,
  })
}

function applyRerun(pipeline: PipelineLike, command: Extract<PersistCommand, { type: 'rerun_clip' }>): PipelineLike {
  clipAt(pipeline, command.clipIndex)
  return pipeline
}

function applyOne(pipeline: PipelineLike, command: PersistCommand): PipelineLike {
  if (command.type === 'select_take') return applySelect(pipeline, command)
  if (command.type === 'tag_clip') return withClip(pipeline, command.clipIndex, { tag: command.tag })
  if (command.type === 'note_clip') return withClip(pipeline, command.clipIndex, { review_notes: command.notes })
  if (command.type === 'rerun_clip') return applyRerun(pipeline, command)
  return pipeline
}

/** Write review decisions onto pipeline JSON fields. Generation records stay read-only. */
export function applyPersistCommands(pipeline: PipelineLike, commands: PersistCommand[]): PipelineLike {
  return commands.reduce(applyOne, pipeline)
}

export function assertRecordProjection(record: TakeRecord, patch: Partial<TakeRecord>): void {
  if (patch.generation_id && patch.generation_id !== record.generation_id) {
    throw new Error('generation_record identity cannot be replaced by the review desk.')
  }
  if (REVIEW_AUTHORITY !== 'projection') {
    throw new Error('Review decisions must not become a second generation authority.')
  }
}
