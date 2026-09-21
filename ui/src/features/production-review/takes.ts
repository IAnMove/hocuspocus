import { filenameOf, finiteNumber, firstText, isTakeStatus, text } from './fields.ts'
import { clipRefs, recordRefs } from './refs.ts'
import { livePipelineStatus } from './status.ts'
import type {
  AttemptLike, PipelineClipLike, ReviewDesk, ReviewShot, ReviewTake, TakeRecord, TakeStatus,
} from './types.ts'

export function shotIdOf(clip: PipelineClipLike): string {
  return text(clip.shot_id) || `clip-${clip.index}`
}

export function attemptsOf(clip: PipelineClipLike): AttemptLike[] {
  if (clip.video_attempts?.length) return clip.video_attempts
  const filename = filenameOf(clip.video_filename)
  if (!filename) return []
  return [{ id: filename, filename, source: 'recovered' }]
}

export function takeIdOf(attempt: AttemptLike, record?: TakeRecord): string {
  return firstText(record?.generation_id, attempt.id, attempt.filename)
}

function inferredStatus(clip: PipelineClipLike, filename: string, pipelineLive: boolean): TakeStatus {
  if (!filename) return pipelineLive ? 'queued' : 'planned'
  if (clip.video_stale) return pipelineLive ? 'queued' : 'failed'
  return 'completed'
}

function durationFrom(attempt: AttemptLike, record: TakeRecord | undefined, clip: PipelineClipLike): number | null {
  const fromRecord = finiteNumber(record?.timestamps?.duration_ms)
  if (fromRecord != null && fromRecord > 0) return fromRecord / 1000
  const seconds = finiteNumber(attempt.duration_seconds)
  if (seconds != null && seconds > 0) return seconds
  const frames = finiteNumber(attempt.video_length), fps = finiteNumber(attempt.fps)
  if (frames != null && frames > 0 && fps != null && fps > 0) return frames / fps
  // Clip-level timing describes the selected clip; planned start/end is not
  // the media duration of every historical take. The preview can probe it.
  if (attempt.filename !== (clip.selected_video_filename || clip.video_filename)) return null
  const fromClip = finiteNumber(clip.duration_seconds)
  return fromClip != null && fromClip > 0 ? fromClip : null
}

export function recordForAttempt(
  attempt: AttemptLike,
  records: TakeRecord[],
  productionId: string,
): TakeRecord | undefined {
  const filename = filenameOf(attempt.filename)
  return records.find(record => {
    if (filenameOf(record.location?.filename) !== filename) return false
    const owner = text(record.production_id)
    return !owner || owner === productionId
  }) || records.find(record => record.generation_id === attempt.id)
}

export function takeFromAttempt(
  attempt: AttemptLike,
  records: TakeRecord[],
  productionId: string,
  clip: PipelineClipLike,
  pipelineLive = false,
): ReviewTake {
  const record = recordForAttempt(attempt, records, productionId)
  const filename = filenameOf(attempt.filename)
  const status = record && isTakeStatus(record.status)
    ? record.status
    : inferredStatus(clip, filename, pipelineLive)
  return {
    id: takeIdOf(attempt, record),
    generationId: record?.generation_id || null,
    filename,
    status,
    durationSeconds: durationFrom(attempt, record, clip),
    notes: '',
    source: attempt.source,
    seed: attempt.seed,
    prompt: firstText(record?.prompt_full, attempt.prompt, clip.video_prompt),
    createdAt: attempt.created_at,
    refs: recordRefs(record).length ? recordRefs(record) : clipRefs(clip),
  }
}

export function clipOwnedFilenames(clip: PipelineClipLike): Set<string> {
  const names = new Set<string>()
  const selected = selectedFilename(clip)
  if (selected) names.add(selected)
  const current = filenameOf(clip.video_filename)
  if (current) names.add(current)
  for (const attempt of attemptsOf(clip)) {
    const name = filenameOf(attempt.filename)
    if (name) names.add(name)
  }
  return names
}

function recordBelongsToClip(
  record: TakeRecord,
  filename: string,
  productionId: string,
  clip: PipelineClipLike,
): boolean {
  const owner = text(record.production_id)
  if (owner && owner !== productionId) return false
  if (clipOwnedFilenames(clip).has(filename)) return true
  if (record.clip_index != null && record.clip_index === clip.index) return true
  const shotId = shotIdOf(clip)
  const recordShot = firstText(record.shot_id, record.cue_id)
  return Boolean(shotId && recordShot && recordShot === shotId)
}

export function extraTakeFromRecord(
  record: TakeRecord,
  productionId: string,
  usedFilenames: Set<string>,
  clip: PipelineClipLike,
): ReviewTake | null {
  const filename = filenameOf(record.location?.filename)
  if (!filename || usedFilenames.has(filename)) return null
  if (!recordBelongsToClip(record, filename, productionId, clip)) return null
  usedFilenames.add(filename)
  return {
    id: record.generation_id,
    generationId: record.generation_id,
    filename,
    status: isTakeStatus(record.status) ? record.status : 'planned',
    durationSeconds: finiteNumber(record.timestamps?.duration_ms) != null
      ? Number(record.timestamps?.duration_ms) / 1000
      : null,
    notes: '',
    prompt: record.prompt_full,
    refs: recordRefs(record),
  }
}

export function selectedFilename(clip: PipelineClipLike): string {
  return filenameOf(clip.selected_video_filename || clip.video_filename)
}

export function selectedTake(clip: PipelineClipLike, takes: ReviewTake[]): ReviewTake | null {
  const filename = selectedFilename(clip)
  if (filename) {
    const match = takes.find(take => take.filename === filename)
    if (match) return match
  }
  return takes[takes.length - 1] || null
}

export function previousTakeId(takes: ReviewTake[], selectedId: string | null | undefined): string | null {
  if (takes.length < 2) return takes.find(take => take.id !== selectedId)?.id || null
  const index = takes.findIndex(take => take.id === selectedId)
  if (index > 0) return takes[index - 1].id
  return takes.find(take => take.id !== selectedId)?.id || null
}

export function findShot(desk: ReviewDesk, shotId: string): ReviewShot {
  const shot = desk.shots.find(item => item.id === shotId)
  if (!shot) throw new Error(`Shot ${shotId} is not in this production.`)
  return shot
}

export function findTake(shot: ReviewShot, takeId: string): ReviewTake {
  const take = shot.takes.find(item => item.id === takeId)
  if (!take) throw new Error(`Take ${takeId} does not belong to shot ${shot.id}.`)
  return take
}

export function selectExactTake(desk: ReviewDesk, shotId: string, takeId: string): ReviewDesk {
  const shot = findShot(desk, shotId)
  const take = findTake(shot, takeId)
  return replaceShot(desk, {
    ...shot,
    selectedTakeId: take.id,
    ...(shot.decision === 'approved' && shot.approvedTakeId !== take.id
      ? { decision: 'pending' as const, approvedTakeId: null } : {}),
    compareTakeId: previousTakeId(shot.takes, take.id),
    durationSeconds: take.durationSeconds ?? shot.durationSeconds,
  })
}

export function replaceShot(desk: ReviewDesk, next: ReviewShot): ReviewDesk {
  return {
    ...desk,
    shots: desk.shots.map(shot => shot.id === next.id ? next : shot),
  }
}

export function comparePair(shot: ReviewShot): { a: ReviewTake | null; b: ReviewTake | null } {
  const a = shot.takes.find(take => take.id === shot.selectedTakeId) || shot.takes[shot.takes.length - 1] || null
  const b = shot.takes.find(take => take.id === shot.compareTakeId) || null
  return { a, b }
}

export function setCompareTake(desk: ReviewDesk, shotId: string, takeId: string): ReviewDesk {
  const shot = findShot(desk, shotId)
  const take = findTake(shot, takeId)
  return replaceShot(desk, { ...shot, compareTakeId: take.id })
}

export function restoreSelections(current: ReviewDesk, projected: ReviewDesk): ReviewDesk {
  return {
    ...projected,
    shots: projected.shots.map(shot => restoreShot(current.shots.find(item => item.id === shot.id), shot)),
  }
}

/** Comparison is local UI state; persisted selections, decisions and notes stay authoritative. */
export function restoreCompareChoices(current: ReviewDesk, projected: ReviewDesk): ReviewDesk {
  if (current.pipelineId !== projected.pipelineId || current.workspace !== projected.workspace) return projected
  return {
    ...projected,
    shots: projected.shots.map(shot => {
      const previous = current.shots.find(item => item.id === shot.id)
      const compare = keepTakeId(shot, previous?.compareTakeId)
      return compare ? { ...shot, compareTakeId: compare } : shot
    }),
  }
}

function restoreShot(previous: ReviewShot | undefined, shot: ReviewShot): ReviewShot {
  if (!previous) return shot
  const selected = keepTakeId(shot, previous.selectedTakeId) || shot.selectedTakeId
  const compare = keepTakeId(shot, previous.compareTakeId) || previousTakeId(shot.takes, selected)
  return {
    ...shot,
    selectedTakeId: selected,
    compareTakeId: compare,
    notes: shot.notes || previous.notes,
    decision: shot.decision === 'pending' ? previous.decision : shot.decision,
    approvedTakeId: shot.approvedTakeId || (shot.decision === 'approved' ? selected : previous.approvedTakeId),
  }
}

function keepTakeId(shot: ReviewShot, takeId: string | null | undefined): string | null {
  if (!takeId) return null
  return shot.takes.some(take => take.id === takeId) ? takeId : null
}

export function pipelineIsLive(status: string | undefined): boolean {
  return livePipelineStatus(status)
}
