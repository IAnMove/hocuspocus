export type ShotTake = {
  id: string
  file: string | null
  selected: boolean
}

export type ShotReview = {
  status: string
  locked: boolean | null
  notes: string | null
  history_id?: string | null
} | null

export type ShotAction = {
  action: string
  enabled: boolean
  reason?: string
}

export type ShotScene = {
  kind: string | null
  id: string | null
} | null

export type ShotMontage = {
  stale: boolean | null
} | null

export type ProductionShot = {
  id: string
  order: number
  start: number | null
  end: number | null
  duration: number | null
  text: string | null
  text_kind: 'lyric' | 'dialogue' | 'action' | null
  takes: ShotTake[]
  selected_take_id: string | null
  review: ShotReview
  technical_status: string | null
  scene: ShotScene
  montage: ShotMontage
  provenance: { source: string }
  actions?: ShotAction[]
}

export type ShotView = {
  workspace_id: string
  production_id: string
  project: { kind: string; id: string } | null
  title: string
  status: string
  format: string | null
  sources: string[]
  limits: string[]
  shots: ProductionShot[]
  shot_count: number
  truncated: boolean
  revision?: number
}
