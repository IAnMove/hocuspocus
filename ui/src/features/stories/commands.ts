import type { CreativeCharacter, CreativeLocation } from '../../lib/labHelpers'
import type { LanguageIntent } from '../../lib/languageIntent'

export interface CreateStoryCommand {
  title: string
  projectType: 'full_story' | 'music_video' | 'trailer' | 'quick_video'
  creativeBrief: string
  premise: string
  logline: string
  synopsis: string
  theme: string
  ending: string
  genre: string
  tone: string
  visualStyle: string
  worldSummary: string
  language: string
  characters: CreativeCharacter[]
  locations: CreativeLocation[]
  outlineBeats: string[]
  durationSeconds?: number
  languageIntent?: LanguageIntent
}

export interface UpdateStoryCommand {
  targetStoryTitle: string
  title: string
  creativeBrief: string
  premise: string
  logline: string
  synopsis: string
  theme: string
  ending: string
  genre: string
  tone: string
  visualStyle: string
  worldSummary: string
  language: string
  characters: CreativeCharacter[]
  locations: CreativeLocation[]
  outlineBeats: string[]
  durationSeconds?: number
  languageIntent?: LanguageIntent
}

export interface GenerateStorySectionCommand {
  targetStoryTitle: string
  scope: 'all' | 'overview' | 'world' | 'characters' | 'relationships' | 'structure'
  instruction: string
  confirm: true
  languageIntent?: LanguageIntent
}

export interface ApplyStoryProposalCommand {
  targetStoryTitle: string
  confirm: true
}

export interface ApproveStorySectionCommand {
  targetStoryTitle: string
  section: 'overview' | 'world' | 'characters' | 'relationships' | 'structure'
  confirm: true
}

export interface StoryVisualSelectionCommand {
  targetKind: 'world' | 'location' | 'character'
  targetName: string
  assetName: string
  primary: boolean
}

export interface ApproveStoryVisualsCommand {
  targetStoryTitle: string
  selections: StoryVisualSelectionCommand[]
  confirm: true
}

export interface GenerateStoryVisualsCommand {
  targetStoryTitle: string
  scope: 'world' | 'locations' | 'characters' | 'all'
  targetNames: string[]
  confirm: true
}

export interface StageStoryComicCommand {
  targetStoryTitle: string
  direction: string
  pageCount: number
  panelsPerPage: number
  confirm: true
  languageIntent?: LanguageIntent
}

export interface StageStoryVideoCommand {
  targetStoryTitle: string
  kind: 'film' | 'trailer'
  direction: string
  durationSeconds?: number
  confirm: true
  languageIntent?: LanguageIntent
}

export interface StartDirectorProductionCommand {
  targetStoryId?: string
  targetStoryTitle: string
  productionId?: string
  kind?: 'film' | 'trailer' | 'music_video'
  confirm: true
}

export interface StageStoryMusicVideoCommand {
  targetStoryId?: string
  targetStoryTitle: string
  songName: string
  cueTitle: string
  cueId?: string
  candidateId?: string
  pacing: 'cinematic' | 'balanced' | 'rhythmic'
  confirm: true
  languageIntent?: LanguageIntent
}

export interface ConfigureStorySongCommand {
  targetStoryId?: string
  targetStoryTitle: string
  songTitle: string
  brief: string
  style: string
  lyrics: string
  writeLyrics: boolean
  lyricsLanguage: string
  instrumental: boolean
  model?: 'music-3.0' | 'music-2.6' | 'minimax_music3' | 'ace_step_v1_5_xl_sft_lm_4b'
  durationSeconds?: number
  languageIntent?: LanguageIntent
}

export interface GenerateStorySongCommand {
  targetStoryId?: string
  targetStoryTitle: string
  cueTitle: string
  cueId?: string
  confirm: true
}
