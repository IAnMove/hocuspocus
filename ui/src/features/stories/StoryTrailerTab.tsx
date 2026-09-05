import { Film } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { type ProductionReviewIssue } from './storyLabChrome'
import type { StoryProject, StoryTrailerFormat, StoryTrailerIntensity, StoryTrailerNarration, StoryTrailerSpoiler } from './types'
import type { AspectRatio, ModelDef, ModelOptions, ResolutionPreset } from '../../types'
import { StoryTrailerClipProduction } from './StoryTrailerClipProduction'
import { StoryTrailerNarrativeForm } from './StoryTrailerNarrativeForm'
import { StoryTrailerTimeline } from './StoryTrailerTimeline'

export type StoryTrailerTabProps = {
  project: StoryProject
  patch: (value: Partial<StoryProject>) => void
  trailerDuration: number
  setTrailerDuration: (value: number) => void
  trailerDirection: string
  setTrailerDirection: (value: string) => void
  trailerTagline: string
  setTrailerTagline: (value: string) => void
  trailerFormat: StoryTrailerFormat
  setTrailerFormat: (value: StoryTrailerFormat) => void
  trailerNarration: StoryTrailerNarration
  setTrailerNarration: (value: StoryTrailerNarration) => void
  trailerSpoiler: StoryTrailerSpoiler
  setTrailerSpoiler: (value: StoryTrailerSpoiler) => void
  trailerIntensity: StoryTrailerIntensity
  setTrailerIntensity: (value: StoryTrailerIntensity) => void
  trailerTitleCards: boolean
  setTrailerTitleCards: (value: boolean) => void
  trailerPreserveVisualStyle: boolean
  setTrailerPreserveVisualStyle: (value: boolean) => void
  markTrailerTouched: () => void
  directVideo: boolean
  directReferenceVideo: boolean
  approvedVisualReferenceCount: number
  directReferenceVideoReady: boolean
  directReferenceVideoSupported: boolean
  directVideoMasterReady: boolean
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
  trailerProductionIssues: ProductionReviewIssue[]
  productionBusy: 'film' | 'music' | 'trailer' | null
  filmGenerationImageReady: boolean
  stageTrailer: (complete: boolean) => void
}

export function StoryTrailerTab(props: StoryTrailerTabProps) {
  const { t } = useUiTranslation('storyLab')
  const { trailerDuration } = props
  return (
    <div className="space-y-4">
      <div className="overflow-hidden rounded-2xl border border-amber-400/30 bg-gradient-to-br from-amber-500/10 via-bg-secondary to-purple-500/10 p-4 md:p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="max-w-2xl">
            <div className="mb-2 flex items-center gap-2 text-amber-200"><Film size={22} /><span className="text-[10px] font-semibold uppercase tracking-[0.2em]">{t('trailer.kicker')}</span></div>
            <h2 className="text-xl font-semibold text-text-primary">{t('trailer.title')}</h2>
            <p className="mt-2 text-xs leading-relaxed text-text-muted">{t('trailer.description')}</p>
          </div>
          <div className="grid min-w-56 grid-cols-2 gap-2 text-center text-[10px]">
            <div className="rounded-lg border border-border bg-bg-primary/50 p-2"><span className="block text-lg font-semibold text-amber-200">{trailerDuration}s</span>{t('trailer.targetDuration')}</div>
            <div className="rounded-lg border border-border bg-bg-primary/50 p-2"><span className="block text-lg font-semibold text-purple-200">6</span>{t('trailer.narrativePhases')}</div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(20rem,0.8fr)]">
        <StoryTrailerNarrativeForm {...props} />
        <StoryTrailerTimeline trailerDuration={trailerDuration} />
      </div>

      <StoryTrailerClipProduction {...props} />
    </div>
  )
}
