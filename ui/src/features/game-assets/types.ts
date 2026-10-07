export type GameGenre = 'platformer' | 'topdown' | 'other'
export type GameView = 'side' | 'topdown'
export type GameSection = 'setup' | 'style' | 'cast' | 'list' | 'produce' | 'review' | 'play' | 'export'
export type PaletteMode = 'locked' | 'free'

export interface GameAttempt {
  id: string
  status: string
  files: Record<string, string>
  decision?: string | null
  note?: string
  metrics?: Record<string, unknown>
  warnings?: string[]
}

export interface GameAsset {
  id: string
  kind: string
  name: string
  description: string
  status: string
  tags: string[]
  spec: Record<string, unknown>
  dependsOn: string[]
  candidates: number
  locked: boolean
  attempts: GameAttempt[]
  approvedAttemptId: string | null
}

export interface GamePixel {
  enabled: boolean
  spriteHeight: number
  tile: number
  colors: number
  outline: string
  dither: string
}

export interface GameAudio {
  genre: string
  instruments: string
  bpm: [number, number]
  musicLufs: number
  sfxPeakDb: number
  sampleRate: number
}

export interface StyleReference {
  assetId: string
  attemptId: string
}

export interface GameStyle {
  revision: number
  approval: 'draft' | 'approved'
  approvedAt: string | null
  preset: string
  traits: string
  negative: string
  palette: string[]
  paletteMode: PaletteMode
  pixel: GamePixel
  light: string
  screen: string
  references: StyleReference[]
  model3d: { maxTriangles: number; texture: number; look: string }
  audio: GameAudio
}

export interface GameExportRecord {
  id: string
  revision: number
  file: string
  createdAt: string
  counts: Record<string, number>
}

export interface Game {
  id: string
  title: string
  revision: number
  createdAt: string
  updatedAt: string
  genre: GameGenre
  view: GameView
  style: GameStyle
  assets: GameAsset[]
  exports: GameExportRecord[]
}

export interface GameLibrary {
  schema: string
  version: number
  games: Game[]
}

export interface StylePreset {
  id: string
  label: { es: string; en: string }
  traits: string
  negative: string
  palette: string[]
  pixel: GamePixel
  screenDefault?: string
  audio: { genre: string; instruments: string; bpm: [number, number] }
}

export interface ProduceStep {
  assetId: string
  kind?: string
  status: string
  reason?: string | null
  error?: string | null
  attemptId?: string
}

export interface ProduceJob {
  id: string
  jobId?: string
  status: string
  message?: string
  gameId?: string
  steps?: ProduceStep[]
}

export interface GameEstimate {
  minutes: number
  source: string
  byKind: Record<string, number>
}

export interface ListProblem {
  line?: number
  code?: string
  message?: string
}

export interface ListReport {
  items: unknown[]
  problems: ListProblem[]
  estimate: GameEstimate
  assets?: GameAsset[]
}

export interface ExportResult {
  file: string
  url: string
  counts: Record<string, number>
  missing: unknown[]
}

export const GAME_SECTIONS: GameSection[] = ['setup', 'style', 'cast', 'list', 'produce', 'review', 'play', 'export']
export const LATER_SECTIONS: GameSection[] = ['play', 'export']
