export interface CatalogProject {
  kind: string
  id: string
}

export interface CatalogReview {
  event: string
  workspace: string
  production_id: string
  project: CatalogProject | null
  series_id?: string
}

export interface CatalogWork {
  workspace_id: string
  production_id: string
  title: string
  status: string
  origin: string
  format: string | null
  project: CatalogProject | null
  series_id: string | null
  linked: boolean
  updated_at: string | null
  preview: string | null
  review: CatalogReview
}

export interface CatalogWarning {
  source: string
  error: string
}

export interface CatalogPage {
  applied: boolean
  works: CatalogWork[]
  total: number
  warnings: CatalogWarning[]
}

export const LIGHT_FORMATS = ['music_video', 'trailer', 'quick_video'] as const
export type LightFormat = typeof LIGHT_FORMATS[number]

export const FORMAT_KEYS = {
  music_video: 'formats.music_video',
  trailer: 'formats.trailer',
  quick_video: 'formats.quick_video',
  full_story: 'formats.full_story',
} as const

export const STATUS_KEYS = {
  pending: 'statuses.pending',
  running: 'statuses.running',
  completed: 'statuses.completed',
  failed: 'statuses.failed',
  unknown: 'statuses.unknown',
} as const

export const ORIGIN_KEYS = {
  mcp: 'origins.mcp',
  wizard: 'origins.wizard',
  ui: 'origins.ui',
  file: 'origins.file',
  link: 'origins.link',
  story: 'origins.story',
  director: 'origins.director',
} as const

export function isFormat(value: string): value is keyof typeof FORMAT_KEYS {
  return Object.prototype.hasOwnProperty.call(FORMAT_KEYS, value)
}

export function isStatus(value: string): value is keyof typeof STATUS_KEYS {
  return Object.prototype.hasOwnProperty.call(STATUS_KEYS, value)
}

export function isOrigin(value: string): value is keyof typeof ORIGIN_KEYS {
  return Object.prototype.hasOwnProperty.call(ORIGIN_KEYS, value)
}
