export const REVIEW_AUTHORITY = 'projection' as const

export type TakeStatus = 'planned' | 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type ReviewDecision = 'pending' | 'approved' | 'rejected'
export type ClipTag = 'good' | 'needs_work' | null

export interface TakeRecord {
  generation_id: string
  production_id?: string | null
  clip_index?: number | null
  shot_id?: string | null
  cue_id?: string | null
  status: TakeStatus
  location?: { filename?: string | null }
  timestamps?: { duration_ms?: number | null }
  prompt_full?: string
  lineage?: { parents?: Array<{ uri?: string | null; kind?: string | null }> }
}

export interface AttemptLike {
  id?: string
  filename: string
  created_at?: number
  seed?: number | null
  prompt?: string
  video_length?: number | null
  fps?: number | null
  duration_seconds?: number | null
  source?: string
}

export interface ClipRefsLike {
  image_references?: string[]
  video_references?: string[]
  audio_references?: string[]
  shot_frame?: string
}

export interface PipelineClipLike {
  index: number
  shot_id?: string
  duration_seconds?: number
  video_filename?: string | null
  selected_video_filename?: string | null
  video_stale?: boolean
  video_attempts?: AttemptLike[]
  tag?: ClipTag
  review_notes?: string
  video_prompt?: string
  image_prompt?: string
  start_image_filename?: string | null
  keyframe_filenames?: string[]
  h3_references?: ClipRefsLike | null
  planned_clip?: { duration_sec?: number; start?: number; end?: number } | null
}

export interface PipelineLike {
  pipeline_id: string
  production_id?: string
  workspace?: string
  scene_description?: string
  status?: string
  clips: PipelineClipLike[]
}

export interface ReviewTake {
  id: string
  generationId: string | null
  filename: string
  status: TakeStatus
  durationSeconds: number | null
  notes: string
  source?: string
  seed?: number | null
  prompt?: string
  createdAt?: number
  refs: string[]
  parentId?: string | null
}

export interface ReviewShot {
  id: string
  clipIndex: number
  durationSeconds: number | null
  notes: string
  decision: ReviewDecision
  selectedTakeId: string | null
  compareTakeId: string | null
  approvedTakeId: string | null
  takes: ReviewTake[]
  refs: string[]
  prompt: string
}

export interface ReviewDesk {
  productionId: string
  pipelineId: string
  workspace: string
  title: string
  shots: ReviewShot[]
}

export type PersistCommand =
  | { type: 'select_take'; pipelineId: string; clipIndex: number; filename: string; takeId: string }
  | { type: 'tag_clip'; pipelineId: string; clipIndex: number; tag: ClipTag }
  | { type: 'note_clip'; pipelineId: string; clipIndex: number; notes: string }
  | { type: 'rerun_clip'; pipelineId: string; clipIndex: number; prompt: string; refs: string[]; parentTakeId: string | null }

export interface RegenJob {
  shotId: string
  clipIndex: number
  prompt: string
  refs: string[]
  parentTakeId: string | null
}

export interface RegenPlan {
  productionId: string
  keepShotIds: string[]
  jobs: RegenJob[]
}

export interface RegenOutcome {
  shotId: string
  ok: boolean
  take?: ReviewTake
  error?: string
}

export interface ExportClip {
  shotId: string
  takeId: string
  filename: string
  durationSeconds: number | null
}

export interface ExportOmission {
  shotId: string
  reason: 'not_approved' | 'queued' | 'not_completed' | 'missing_filename'
}

export interface ExportSelection {
  productionId: string
  clips: ExportClip[]
  omitted: ExportOmission[]
}

export interface ActivityOpenSource {
  kind?: string
  id?: string
  title?: string
  pipeline_id?: string
  project?: { kind?: string; id?: string }
  metadata?: Record<string, unknown>
  primary?: {
    pipeline_id?: string
    metadata?: Record<string, unknown>
  }
}
