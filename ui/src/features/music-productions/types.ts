export interface MusicProductionCard {
  production_id: string
  status: string
  title: string
  duration: number | null
  contact_sheet: string | null
  montage: string | null
  video: string | null
  editable: { montage?: string | null; manifest?: string; scene_docs?: number; warnings?: number } | null
}

/** One row of `<id>.shots.json`, as `write_manifest` stored it. */
export interface MusicProductionTake {
  file: string
  take?: number
  verdict?: string
  r?: number | null
  drive?: string
}

export type MusicProductionReviewStatus = 'pending' | 'approved' | 'changes_requested'

export type ShotReviewAction = 'approved' | 'changes_requested' | 'lock' | 'unlock'

export interface MusicProductionShotReview {
  status?: MusicProductionReviewStatus
  locked?: boolean
}

export interface MusicProductionShot {
  key: string
  kind?: string
  start?: number
  end?: number
  sung?: boolean
  lyric?: string
  frame_prompt?: string
  action?: string
  seed?: number
  cast?: string[]
  start_frame?: string | null
  clip?: string | null
  clip_qa?: Record<string, unknown>
  takes?: MusicProductionTake[]
  scene_doc?: string | null
  scene_video?: string | null
  warnings?: unknown[]
  review?: MusicProductionShotReview
}

export interface MusicProductionDetail {
  production: MusicProductionCard
  status: Record<string, unknown>
  shots: MusicProductionShot[]
}
