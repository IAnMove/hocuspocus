import { ChevronRight, Loader2, Sparkles } from 'lucide-react'
import { MINIMAX_IMAGE_API_LABEL, MINIMAX_IMAGE_API_MODEL } from '../../lib/externalModels'
import { useUiTranslation } from '../../i18n'
import { button, completeGenerationButton, input, panel, requiredInput } from './storyLabChrome'
import { StoryVideoFormatControls } from './StoryVideoFormatControls'
import type { StoryTrailerTabProps } from './StoryTrailerTab'

export function StoryTrailerClipProduction(props: StoryTrailerTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, patch, trailerTitleCards, trailerPreserveVisualStyle, setTrailerPreserveVisualStyle, markTrailerTouched,
    directVideo, directReferenceVideo, approvedVisualReferenceCount, directReferenceVideoReady, directReferenceVideoSupported,
    directVideoMasterReady, filmImageModel, filmVideoModel, selectableImageModels, selectableVideoModels,
    selectedFilmImageModel, selectedFilmVideoModel, selectDirectorImageModel, selectStoryVideoModel, storyVideoOptionsReady,
    storyVideoConfigurationReady, storyVideoResolution, storyVideoAspectRatio, storyVideoOptions, storyVideoAdjusted,
    setStoryVideoFormat, trailerProductionIssues, productionBusy, filmGenerationImageReady, stageTrailer,
  } = props
  return (
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
  )
}
