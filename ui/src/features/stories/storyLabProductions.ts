import type { RefObject } from 'react'
import type { AspectRatio, ModelDef, ModelOptions, ResolutionPreset } from '../../types'
import type { ProductionReviewIssue, StoryLabTab } from './storyLabChrome'
import type { StoryMusicCandidateOption } from './storyLabMusic'
import type { StoryProject, StoryWritingProvider } from './types'

export type StoryProductionBusy = 'film' | 'music' | 'trailer' | null
export type StoryMusicProductionMode = 'full' | 'trailer'
export type StoryMusicProductionPacing = 'cinematic' | 'balanced' | 'rhythmic'

export type StoryProductionsTabProps = {
  project: StoryProject
  patch: (value: Partial<StoryProject>) => void
  workspace: string
  productionBusy: StoryProductionBusy
  comicDirection: string
  setComicDirection: (value: string) => void
  comicPageCount: number
  setComicPageCount: (value: number) => void
  comicPanelsPerPage: number
  setComicPanelsPerPage: (value: number) => void
  stageComic: (complete: boolean) => void
  filmDirection: string
  setFilmDirection: (value: string) => void
  filmDuration: number
  setFilmDuration: (value: number) => void
  filmPreserveVisualStyle: boolean
  setFilmPreserveVisualStyle: (value: boolean) => void
  stageFilm: (complete: boolean) => void
  musicProductionCandidateId: string
  setMusicProductionCandidateId: (value: string) => void
  musicCandidateOptions: StoryMusicCandidateOption[]
  selectedMusicOption?: StoryMusicCandidateOption
  musicProductionMode: StoryMusicProductionMode
  setMusicProductionMode: (value: StoryMusicProductionMode) => void
  musicProductionPacing: StoryMusicProductionPacing
  setMusicProductionPacing: (value: StoryMusicProductionPacing) => void
  musicTrailerRange: { start: number; end: number; duration: number }
  setMusicTrailerRange: (range: { start: number; end: number; duration: number }) => void
  stageMusicVideo: (complete: boolean) => void
  setMusicWritingProvider: (value: StoryWritingProvider) => void
  patchMusicWritingProvider: (value: Partial<StoryProject['provider']>) => void
  directVideo: boolean
  directMusicVideo: boolean
  directReferenceVideo: boolean
  approvedVisualReferenceCount: number
  directReferenceVideoReady: boolean
  directReferenceVideoSupported: boolean
  directVideoMasterReady: boolean
  protagonistReferenceReady: boolean
  musicWritingReady: boolean
  musicVideoImageReady: boolean
  filmImageReady: boolean
  filmGenerationImageReady: boolean
  filmImageModel: string
  filmVideoModel: string
  selectableImageModels: ModelDef[]
  selectableVideoModels: ModelDef[]
  selectedFilmImageModel?: ModelDef
  selectedFilmVideoModel?: ModelDef
  selectDirectorImageModel: (model: string) => void
  selectStoryVideoModel: (model: string) => void
  storyVideoOptionsReady: boolean
  storyVideoConfigurationReady: boolean
  storyVideoResolution: ResolutionPreset
  storyVideoAspectRatio: AspectRatio
  storyVideoOptions: ModelOptions | null
  storyVideoAdjusted: boolean
  setStoryVideoFormat: (resolution: ResolutionPreset, aspectRatio: AspectRatio) => void
  productionIssues: ProductionReviewIssue[]
  musicProductionIssues: ProductionReviewIssue[]
  visibleProductionIssues: ProductionReviewIssue[]
  onNavigate: (tab: StoryLabTab) => void
  onOpenIssue: (issue: ProductionReviewIssue) => void
  minimaxConfigured: boolean
  musicCoverRef: RefObject<HTMLInputElement | null>
  uploadCoverReference: (file?: File) => void
  writeStorySong: () => void
  adaptStoryLyrics: () => void
  generateMinimaxSongs: () => void
  openMusicalTrailer: (candidateId?: string) => void
}
