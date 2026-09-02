import { ChevronRight, Film, Loader2, Sparkles } from 'lucide-react'
import { MINIMAX_IMAGE_API_LABEL, MINIMAX_IMAGE_API_MODEL } from '../../lib/externalModels'
import { useUiTranslation } from '../../i18n'
import { button, completeGenerationButton, input, panel, requiredInput, type ProductionReviewIssue } from './storyLabChrome'
import { StoryVideoFormatControls } from './StoryVideoFormatControls'
import type { StoryProject, StoryTrailerFormat, StoryTrailerIntensity, StoryTrailerNarration, StoryTrailerSpoiler } from './types'
import type { AspectRatio, ModelDef, ModelOptions, ResolutionPreset } from '../../types'

const TRAILER_ARC = [
  { key: 'impact', start: 0, end: 10 },
  { key: 'promise', start: 10, end: 30 },
  { key: 'rupture', start: 30, end: 50 },
  { key: 'escalation', start: 50, end: 80 },
  { key: 'breath', start: 80, end: 90 },
  { key: 'hook', start: 90, end: 100 },
] as const

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

export function StoryTrailerTab({
  project, patch, trailerDuration, setTrailerDuration, trailerDirection, setTrailerDirection, trailerTagline,
  setTrailerTagline, trailerFormat, setTrailerFormat, trailerNarration, setTrailerNarration, trailerSpoiler,
  setTrailerSpoiler, trailerIntensity, setTrailerIntensity, trailerTitleCards, setTrailerTitleCards,
  trailerPreserveVisualStyle, setTrailerPreserveVisualStyle, markTrailerTouched, directVideo, directReferenceVideo,
  approvedVisualReferenceCount, directReferenceVideoReady, directReferenceVideoSupported, directVideoMasterReady,
  filmImageModel, filmVideoModel, selectableImageModels, selectableVideoModels, selectedFilmImageModel,
  selectedFilmVideoModel, selectDirectorImageModel, selectStoryVideoModel, storyVideoOptionsReady,
  storyVideoConfigurationReady, storyVideoResolution, storyVideoAspectRatio, storyVideoOptions, storyVideoAdjusted,
  setStoryVideoFormat, trailerProductionIssues, productionBusy, filmGenerationImageReady, stageTrailer,
}: StoryTrailerTabProps) {
  const { t } = useUiTranslation('storyLab')
  const arcCopy: Record<(typeof TRAILER_ARC)[number]['key'], { label: string; detail: string }> = {
    impact: { label: t('trailer.arcImpact'), detail: t('trailer.arcImpactDetail') },
    promise: { label: t('trailer.arcPromise'), detail: t('trailer.arcPromiseDetail') },
    rupture: { label: t('trailer.arcRupture'), detail: t('trailer.arcRuptureDetail') },
    escalation: { label: t('trailer.arcEscalation'), detail: t('trailer.arcEscalationDetail') },
    breath: { label: t('trailer.arcBreath'), detail: t('trailer.arcBreathDetail') },
    hook: { label: t('trailer.arcHook'), detail: t('trailer.arcHookDetail') },
  }
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
        <div className={`${panel} space-y-4`}>
          <div><h3 className="text-sm font-semibold text-text-primary">{t('trailer.narrativeDirection')}</h3><p className="mt-1 text-[10px] text-text-muted">{t('trailer.narrativeHint')}</p></div>
          <label className="block text-[10px] text-text-muted">{t('trailer.promiseLabel')}
            <textarea className={`${input} mt-1`} rows={4} value={trailerDirection} onChange={event => { markTrailerTouched(); setTrailerDirection(event.target.value) }} aria-label={t('trailer.directionAria')} />
          </label>
          <label className="block text-[10px] text-text-muted">{t('trailer.optionalTagline')}
            <input className={`${input} mt-1`} value={trailerTagline} onChange={event => { markTrailerTouched(); setTrailerTagline(event.target.value) }} placeholder={project.logline || t('trailer.taglinePlaceholder')} />
          </label>
          <div>
            <p className="mb-1.5 text-[10px] text-text-muted">{t('trailer.duration')}</p>
            <div className="grid grid-cols-4 gap-1.5">
              {[30, 45, 60, 90].map(seconds => <button key={seconds} type="button" className={`${button} ${trailerDuration === seconds ? 'border-amber-400/70 bg-amber-500/10 text-amber-100' : ''}`} onClick={() => { markTrailerTouched(); setTrailerDuration(seconds) }}>{seconds}s</button>)}
            </div>
            <input className={`${input} mt-2`} type="number" min={15} max={180} step={5} value={trailerDuration} onChange={event => { markTrailerTouched(); setTrailerDuration(Math.max(15, Math.min(180, Number(event.target.value) || 60))) }} />
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <label className="block text-[10px] text-text-muted">{t('trailer.format')}
              <select className={`${input} mt-1`} value={trailerFormat} onChange={event => { markTrailerTouched(); setTrailerFormat(event.target.value as StoryTrailerFormat) }}>
                <option value="theatrical">{t('trailer.formatTheatrical')}</option>
                <option value="teaser">{t('trailer.formatTeaser')}</option>
                <option value="character">{t('trailer.formatCharacter')}</option>
              </select>
            </label>
            <label className="block text-[10px] text-text-muted">{t('trailer.voices')}
              <select className={`${input} mt-1`} value={trailerNarration} onChange={event => { markTrailerTouched(); setTrailerNarration(event.target.value as StoryTrailerNarration) }}>
                <option value="hybrid">{t('trailer.voicesHybrid')}</option>
                <option value="voice_over">{t('trailer.voicesVoiceOver')}</option>
                <option value="dialogue">{t('trailer.voicesDialogue')}</option>
                <option value="visual">{t('trailer.voicesVisual')}</option>
              </select>
            </label>
            <label className="block text-[10px] text-text-muted">{t('trailer.spoiler')}
              <select className={`${input} mt-1`} value={trailerSpoiler} onChange={event => { markTrailerTouched(); setTrailerSpoiler(event.target.value as StoryTrailerSpoiler) }}>
                <option value="mystery">{t('trailer.spoilerMystery')}</option>
                <option value="balanced">{t('trailer.spoilerBalanced')}</option>
                <option value="revealing">{t('trailer.spoilerRevealing')}</option>
              </select>
            </label>
            <label className="block text-[10px] text-text-muted">{t('trailer.intensity')}
              <select className={`${input} mt-1`} value={trailerIntensity} onChange={event => { markTrailerTouched(); setTrailerIntensity(event.target.value as StoryTrailerIntensity) }}>
                <option value="rising">{t('trailer.intensityRising')}</option>
                <option value="relentless">{t('trailer.intensityRelentless')}</option>
                <option value="prestige">{t('trailer.intensityPrestige')}</option>
              </select>
            </label>
          </div>
          <label className={`flex items-start gap-2 rounded-md border p-2 ${trailerTitleCards && !project.allowClipText ? 'border-amber-400/50 bg-amber-500/10' : 'border-border bg-bg-primary/30'}`}>
            <input type="checkbox" checked={trailerTitleCards} onChange={event => { markTrailerTouched(); setTrailerTitleCards(event.target.checked) }} className="mt-0.5 accent-amber-400" />
            <span><span className="block text-[10px] font-medium text-text-primary">{t('trailer.titleCards')}</span><span className="block text-[9px] text-text-muted">{t('trailer.titleCardsHint')}</span></span>
          </label>
          {trailerTitleCards && !project.allowClipText && <button type="button" className={`${button} w-full border-amber-400/50 text-amber-200`} onClick={() => patch({ allowClipText: true })}>{t('trailer.allowClipText')}</button>}
        </div>

        <div className={`${panel} space-y-3`}>
          <div><h3 className="text-sm font-semibold text-text-primary">{t('trailer.timeline')}</h3><p className="mt-1 text-[10px] text-text-muted">{t('trailer.timelineHint')}</p></div>
          {TRAILER_ARC.map((phase, index) => {
            const start = Math.round(trailerDuration * phase.start / 100)
            const end = Math.round(trailerDuration * phase.end / 100)
            const copy = arcCopy[phase.key]
            return <div key={phase.key} className="grid grid-cols-[2rem_minmax(0,1fr)_3.5rem] items-start gap-2 rounded-lg border border-border bg-bg-primary/35 p-2.5">
              <span className="flex h-6 w-6 items-center justify-center rounded-full bg-amber-500/15 text-[10px] font-semibold text-amber-200">{index + 1}</span>
              <span><span className="block text-[10px] font-medium text-text-primary">{copy.label}</span><span className="mt-0.5 block text-[9px] leading-relaxed text-text-muted">{copy.detail}</span></span>
              <span className="text-right text-[9px] font-medium text-amber-200">{start}–{end}s</span>
            </div>
          })}
        </div>
      </div>

      <div className={`${panel} space-y-4`}>
        <div><h3 className="text-sm font-semibold text-text-primary">{t('trailer.clipProduction')}</h3><p className="mt-1 text-[10px] text-text-muted">{t('trailer.clipProductionHint')}</p></div>
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-lg border border-border bg-bg-primary/30 p-3 space-y-2">
            <p className="text-[10px] font-medium text-text-primary">{t('trailer.visualGuide')}</p>
            <p className="text-[9px] leading-relaxed text-text-muted">{t('trailer.visualGuideHint')}</p>
            <div className="grid gap-1.5 md:grid-cols-3">
              <button type="button" className={`${button} flex-col ${!directVideo && !directReferenceVideo ? 'border-purple-400/60 text-purple-200' : ''}`} onClick={() => patch({ musicVideoGenerationMode: 'image_guided' })}><span>{t('trailer.startImages')}</span><span className="text-[9px] text-text-muted">{t('trailer.startImagesHint')}</span></button>
              <button type="button" className={`${button} flex-col ${directReferenceVideo ? 'border-violet-400/70 bg-violet-500/10 text-violet-200' : ''}`} onClick={() => patch({ musicVideoGenerationMode: 'direct_references' })}><span>{t('trailer.directReferences')}</span><span className="text-[9px] text-text-muted">{t('trailer.directReferencesHint')}</span></button>
              <button type="button" className={`${button} flex-col ${directVideo ? 'border-fuchsia-400/70 bg-fuchsia-500/10 text-fuchsia-200' : ''}`} onClick={() => patch({ musicVideoGenerationMode: 'direct_video', protagonistConsistency: false })}><span>{t('trailer.directVideo')}</span><span className="text-[9px] text-text-muted">{t('trailer.directVideoHint')}</span></button>
            </div>
            {project.protagonistConsistency && <p className="text-[9px] text-amber-300">{t('trailer.t2vDisablesConsistency')}</p>}
            {directReferenceVideo && <div className={`rounded-md border p-2 text-[9px] leading-relaxed ${directReferenceVideoReady ? 'border-emerald-500/35 bg-emerald-500/5 text-emerald-100' : 'border-amber-500/40 bg-amber-500/5 text-amber-200'}`}>
              {directReferenceVideoReady
                ? t('trailer.refsReady', { count: approvedVisualReferenceCount })
                : directReferenceVideoSupported
                  ? t('trailer.approveInAssets')
                  : t('trailer.h3Required')}
            </div>}
            {directVideo && <div className="rounded-md border border-fuchsia-500/30 bg-fuchsia-500/10 p-2 space-y-2">
              <p className="text-[10px] font-medium text-fuchsia-200">{t('trailer.t2vTitle')}</p>
              <p className="text-[9px] leading-relaxed text-text-muted">{t('trailer.t2vHint')}</p>
              <label className="block text-[9px] text-violet-200">{t('trailer.masterPrompt')}<span className="ml-1 text-violet-300" title={t('chrome.required')}>●</span>
                <textarea className={`${input} ${requiredInput} mt-1 min-h-32 resize-y leading-relaxed`} value={project.directVideoMasterPrompt}
                  onChange={event => patch({ directVideoMasterPromptMode: 'custom', directVideoMasterPrompt: event.target.value })}
                  placeholder={t('trailer.masterPlaceholder')} required aria-required="true" />
              </label>
              <span className={`block text-[9px] leading-relaxed ${directVideoMasterReady ? 'text-fuchsia-200/80' : 'text-amber-300'}`}>
                {directVideoMasterReady ? t('trailer.t2vReady') : t('trailer.completeMaster')}
              </span>
            </div>}
            <label className={`flex items-start gap-2 pt-1 ${directVideo ? 'opacity-45' : ''}`}><input type="checkbox" disabled={directVideo} checked={trailerPreserveVisualStyle} onChange={event => { markTrailerTouched(); setTrailerPreserveVisualStyle(event.target.checked) }} className="mt-0.5 accent-purple-400" /><span><span className="block text-[10px] text-text-primary">{t('trailer.keepStoryStyle')}</span><span className="block text-[9px] text-text-muted">{directVideo ? t('trailer.styleFromMaster') : t('trailer.styleKeepsMedium')}</span></span></label>
          </div>
          <div className="rounded-lg border border-border bg-bg-primary/30 p-3 space-y-2">
            <label className="block text-[10px] text-text-muted">{t('trailer.imageModel')}
              <select className={`${input} mt-1`} value={filmImageModel} disabled={directVideo || directReferenceVideo} onChange={event => selectDirectorImageModel(event.target.value)}>
                {filmImageModel !== MINIMAX_IMAGE_API_MODEL && !selectableImageModels.some(model => model.model_type === filmImageModel) && <option value={filmImageModel}>{selectedFilmImageModel?.name || filmImageModel}</option>}
                <optgroup label={t('trailer.externalApi')}><option value={MINIMAX_IMAGE_API_MODEL}>{MINIMAX_IMAGE_API_LABEL}</option></optgroup>
                <optgroup label={t('trailer.localModels')}>{selectableImageModels.map(model => <option key={model.model_type} value={model.model_type}>{model.name}{model.is_downloaded === false ? t('trailer.downloadsOnFirstUse') : ''}</option>)}</optgroup>
              </select>
            </label>
            <label className="block text-[10px] text-text-muted">{t('trailer.videoModel')}
              <select className={`${input} mt-1`} value={filmVideoModel} disabled={project.provider.useGlobalProfile || !storyVideoOptionsReady} onChange={event => selectStoryVideoModel(event.target.value)}>
                {!selectableVideoModels.some(model => model.model_type === filmVideoModel) && <option value={filmVideoModel}>{selectedFilmVideoModel?.name || filmVideoModel}</option>}
                {selectableVideoModels.map(model => <option key={model.model_type} value={model.model_type}>{model.name}{model.is_downloaded === false ? t('trailer.downloadsOnFirstUse') : ''}</option>)}
              </select>
            </label>
          </div>
        </div>
        <StoryVideoFormatControls videoModel={filmVideoModel} resolution={storyVideoResolution} aspectRatio={storyVideoAspectRatio} options={storyVideoOptions} disabled={!storyVideoOptionsReady} inherited={project.provider.useGlobalProfile} adjusted={storyVideoAdjusted} onChange={setStoryVideoFormat} />
        {trailerProductionIssues.length > 0 && <div className="rounded-md border border-amber-400/30 bg-amber-500/10 p-2 text-[10px] text-amber-200">{t('trailer.reviewRequirements', { count: trailerProductionIssues.length })}</div>}
        <div className="grid gap-2 sm:grid-cols-2">
          <button className={`${button} ${completeGenerationButton} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(trailerProductionIssues.length) || Boolean(productionBusy) || !filmGenerationImageReady || !directReferenceVideoReady || !directVideoMasterReady || !storyVideoConfigurationReady || (trailerTitleCards && !project.allowClipText)} onClick={() => void stageTrailer(true)}>{productionBusy === 'trailer' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {t('trailer.generateFull')}</button>
          <button className={`${button} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(trailerProductionIssues.length) || Boolean(productionBusy) || !directVideoMasterReady || !storyVideoConfigurationReady || (trailerTitleCards && !project.allowClipText)} onClick={() => void stageTrailer(false)}><ChevronRight size={13} /> {t('trailer.openDirector')}</button>
        </div>
        <p className="text-[9px] text-text-muted">{t('trailer.generationHint')}</p>
      </div>
    </div>
  )
}
