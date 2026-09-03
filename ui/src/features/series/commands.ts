import type { CreativeCharacter, CreativeLocation } from '../../lib/labHelpers'
import type { LanguageIntent } from '../../lib/languageIntent'

export interface CreateSeriesEpisodeCommand {
  seriesTitle: string
  seriesPremise: string
  seriesLogline: string
  episodeTitle: string
  episodePremise: string
  episodeLogline: string
  genre: string
  tone: string
  visualStyle: string
  worldSummary: string
  theme: string
  ending: string
  language: string
  characters: CreativeCharacter[]
  locations: CreativeLocation[]
  outlineBeats: string[]
  targetDurationSeconds?: number
  createIfMissing: boolean
  knownUniverse: boolean
  languageIntent?: LanguageIntent
}

export interface UpdateSeriesEpisodeCommand {
  seriesTitle: string
  targetEpisodeTitle: string
  episodeTitle: string
  episodePremise: string
  episodeLogline: string
  outlineBeats: string[]
  targetDurationSeconds?: number
  languageIntent?: LanguageIntent
}

export interface GenerateSeriesPlanCommand {
  seriesTitle: string
  targetEpisodeTitle: string
  scope: 'outline' | 'script' | 'shots' | 'complete'
  instruction: string
  confirm: true
  languageIntent?: LanguageIntent
}

export interface ApplySeriesPlanCommand {
  seriesTitle: string
  targetEpisodeTitle: string
  jobId: string
  confirm: true
}

export interface RenderSeriesShotsCommand {
  seriesTitle: string
  targetEpisodeTitle: string
  mode: 'selected' | 'missing' | 'failed' | 'all'
  shotIds: string[]
  seed?: number
  confirm: true
}

export interface ReviewSeriesAttemptsCommand {
  seriesTitle: string
  targetEpisodeTitle: string
  decision: 'approve' | 'reject'
  scope: 'selected_latest' | 'all_latest'
  shotNumbers: number[]
  attemptId: string
  confirm: true
}

export interface AssembleSeriesEpisodeCommand {
  seriesTitle: string
  targetEpisodeTitle: string
  confirm: true
}

export interface CommitSeriesCanonCommand {
  seriesTitle: string
  targetEpisodeTitle: string
  decision: 'accept_all' | 'reject_all' | 'accept_selected' | 'reject_selected'
  itemIds: string[]
  confirm: true
}

/** Stage the exact Series episode as an editable Comics project. */
export interface StageSeriesComicCommand {
  seriesId: string
  episodeId: string
  title?: string
  pageCount?: number
  panelsPerPage?: number
  confirm: true
}
