export type GameGenre = 'platformer' | 'topdown' | 'other'
export type GameView = 'side' | 'topdown'
export type GameSection = 'setup' | 'style' | 'cast' | 'list' | 'produce' | 'review' | 'play' | 'export'
export type PaletteMode = 'locked' | 'free'

/** A warning is a code, or ``{code, message?, file?, candidate?}``. */
export type GameWarning = string | { code?: string; message?: string; file?: string; candidate?: string }

export interface GameAttempt {
  id: string
  status: string
  files: Record<string, string>
  decision?: string | null
  note?: string
  metrics?: Record<string, unknown>
  warnings?: GameWarning[]
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
  updatedAt?: string
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

export type StylePatch = Partial<Omit<GameStyle, 'pixel' | 'audio' | 'model3d'>> & {
  pixel?: Partial<GamePixel>
  audio?: Partial<GameAudio>
  model3d?: Partial<GameStyle['model3d']>
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

/** Setup and style edits that are not on the server yet. */
export type GamePatch = Partial<Pick<Game, 'title' | 'genre' | 'view'>> & { style?: StylePatch }

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
  error?: string | null
  gameId?: string
  steps?: ProduceStep[]
}

export interface GameEstimate {
  minutes: number
  source: string
  byKind: Record<string, number>
}

/** One server problem. ``line`` is 1-based; 0 means the whole list. */
export interface GameProblem {
  line?: number
  code?: string
  field?: string
  message?: string
  [detail: string]: unknown
}

export type ListProblem = GameProblem

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
export const LATER_SECTIONS: GameSection[] = []
