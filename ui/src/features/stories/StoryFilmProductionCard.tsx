import { ChevronRight, Film, Loader2, Sparkles } from 'lucide-react'
import { MINIMAX_IMAGE_API_LABEL, MINIMAX_IMAGE_API_MODEL } from '../../lib/externalModels'
import { useUiTranslation } from '../../i18n'
import { QuickVideoBatchPanel } from './QuickVideoBatchPanel'
import { button, completeGenerationButton, input, panel } from './storyLabChrome'
import { StoryVideoFormatControls } from './StoryVideoFormatControls'
import type { StoryProductionsTabProps } from './storyLabProductions'

export function StoryFilmProductionCard(props: StoryProductionsTabProps) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, patch, workspace, productionBusy, filmDirection, setFilmDirection, filmDuration, setFilmDuration,
    filmPreserveVisualStyle, setFilmPreserveVisualStyle, stageFilm, directVideo, directReferenceVideo,
    approvedVisualReferenceCount, directReferenceVideoReady, directReferenceVideoSupported, filmGenerationImageReady,
    filmImageReady, filmImageModel, filmVideoModel, selectableImageModels, selectableVideoModels,
    selectedFilmImageModel, selectedFilmVideoModel, selectDirectorImageModel, selectStoryVideoModel, storyVideoOptionsReady,
    storyVideoConfigurationReady, storyVideoResolution, storyVideoAspectRatio, storyVideoOptions, storyVideoAdjusted,
    setStoryVideoFormat, productionIssues,
  } = props
  return (
    <div className={`${panel} space-y-3`}>
      <Film size={26} className="text-purple-400" />
      <h3 className="font-semibold text-text-primary">{project.projectType === 'quick_video' ? t('productions.quickVideo') : t('productions.filmTitle')}</h3>
      <p className="text-xs text-text-muted">{project.projectType === 'quick_video' ? t('productions.quickHint') : t('productions.filmHint')}</p>
      <textarea className={input} rows={4} value={filmDirection} onChange={event => setFilmDirection(event.target.value)} aria-label={t('productions.filmDirectionAria')} />
      <label className="block text-[10px] text-text-muted">{t('productions.targetDuration')}
        <input className={`${input} mt-1`} type="number" min={10} max={1800} step={5} value={filmDuration}
          onChange={event => setFilmDuration(Math.max(10, Math.min(1800, Number(event.target.value) || 45)))} />
      </label>
      <div className="rounded-md border border-violet-500/25 bg-violet-500/5 p-2.5 space-y-2">
        <p className="text-[10px] font-medium text-violet-100">{t('productions.visualGuidance')}</p>
        <div className="grid grid-cols-2 gap-1.5">
          <button type="button" className={`${button} flex-col ${!directReferenceVideo ? 'border-purple-400/60 text-purple-200' : ''}`}
            onClick={() => patch({ musicVideoGenerationMode: 'image_guided' })}>
            <span>{t('productions.generateStartImages')}</span>
            <span className="text-[9px] text-text-muted">{t('productions.imageGuidedHint')}</span>
          </button>
          <button type="button" className={`${button} flex-col ${directReferenceVideo ? 'border-violet-400/70 bg-violet-500/10 text-violet-200' : ''}`}
            onClick={() => patch({ musicVideoGenerationMode: 'direct_references' })}>
            <span>{t('productions.directApproved')}</span>
            <span className="text-[9px] text-text-muted">{t('productions.h3NoStart')}</span>
          </button>
          <button type="button" className={`${button} flex-col ${directVideo ? 'border-fuchsia-400/70 bg-fuchsia-500/10 text-fuchsia-200' : ''}`}
            onClick={() => patch({ musicVideoGenerationMode: 'direct_video', protagonistConsistency: false })}>
            <span>{t('productions.directVideo')}</span>
            <span className="text-[9px] text-text-muted">{t('productions.t2vNoRefs')}</span>
          </button>
        </div>
        {(directReferenceVideo || directVideo) && (
          <p className={`text-[9px] ${directReferenceVideoReady ? 'text-emerald-200' : 'text-amber-300'}`}>
            {directVideo
              ? t('productions.t2vNoImage')
              : directReferenceVideoReady
                ? t('productions.refsReadyH3', { count: approvedVisualReferenceCount })
                : directReferenceVideoSupported
                  ? t('productions.approveInAssets')
                  : t('productions.chooseH3')}
          </p>
        )}
      </div>
      <label className="block text-[10px] text-text-muted">{t('productions.imageModel')}
        <select className={`${input} mt-1`} value={filmImageModel} disabled={directReferenceVideo || directVideo}
          onChange={event => selectDirectorImageModel(event.target.value)}>
          {filmImageModel !== MINIMAX_IMAGE_API_MODEL && !selectableImageModels.some(model => model.model_type === filmImageModel) && (
            <option value={filmImageModel}>{selectedFilmImageModel?.name || filmImageModel}</option>
          )}
          <optgroup label={t('productions.externalApi')}>
            <option value={MINIMAX_IMAGE_API_MODEL}>{MINIMAX_IMAGE_API_LABEL}</option>
          </optgroup>
          <optgroup label={t('productions.localModels')}>
            {selectableImageModels.map(model => (
              <option key={model.model_type} value={model.model_type}>
                {model.name}{model.is_downloaded === false ? t('productions.downloadsOnFirstUse') : ''}
              </option>
            ))}
          </optgroup>
        </select>
        <span className={`mt-1 block text-[9px] leading-relaxed ${filmImageReady ? 'text-text-muted' : 'text-amber-300'}`}>
          {directVideo
            ? t('productions.notUsedDirectVideo')
            : directReferenceVideo
              ? t('productions.notUsedDirectRefs')
              : filmImageModel === MINIMAX_IMAGE_API_MODEL
                ? filmImageReady ? t('productions.minimaxImageReady') : t('productions.minimaxImageMissing')
                : t('productions.localImageHint')}
        </span>
      </label>
      <label className="block text-[10px] text-text-muted">{t('productions.videoModel')}
        <select className={`${input} mt-1`} value={filmVideoModel}
          disabled={project.provider.useGlobalProfile || !storyVideoOptionsReady}
          onChange={event => selectStoryVideoModel(event.target.value)}>
          {!selectableVideoModels.some(model => model.model_type === filmVideoModel) && (
            <option value={filmVideoModel}>{selectedFilmVideoModel?.name || filmVideoModel}</option>
          )}
          {selectableVideoModels.map(model => (
            <option key={model.model_type} value={model.model_type}>
              {model.name}{model.is_downloaded === false ? t('productions.downloadsOnFirstUse') : ''}
            </option>
          ))}
        </select>
        <span className="mt-1 block text-[9px] leading-relaxed text-text-muted">
          {!storyVideoOptionsReady
            ? t('productions.checkingFormats')
            : project.provider.useGlobalProfile
              ? t('productions.inheritedProfile')
              : filmVideoModel === 'minimax_h3_legacy'
                ? t('productions.h3LegacyHint')
                : filmVideoModel.startsWith('minimax_h3')
                  ? t('productions.h3Hint')
                  : t('productions.ltxHint')}
        </span>
      </label>
      <StoryVideoFormatControls
        videoModel={filmVideoModel}
        resolution={storyVideoResolution}
        aspectRatio={storyVideoAspectRatio}
        options={storyVideoOptions}
        disabled={!storyVideoOptionsReady}
        inherited={project.provider.useGlobalProfile}
        adjusted={storyVideoAdjusted}
        onChange={setStoryVideoFormat}
      />
      <label className="flex items-start gap-2 rounded-md border border-purple-500/30 bg-purple-500/10 p-2 cursor-pointer">
        <input type="checkbox" checked={filmPreserveVisualStyle} onChange={event => setFilmPreserveVisualStyle(event.target.checked)} className="mt-0.5 accent-purple-400" />
        <span>
          <span className="block text-[10px] font-medium text-purple-200">{t('productions.preserveStyle')}</span>
          <span className="block text-[9px] leading-relaxed text-text-muted">{t('productions.preserveStyleHint')}</span>
        </span>
      </label>
      <button className={`${button} ${completeGenerationButton} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length) || Boolean(productionBusy) || !filmGenerationImageReady || !directReferenceVideoReady || !storyVideoConfigurationReady} onClick={() => stageFilm(true)}>{productionBusy === 'film' ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} {project.projectType === 'quick_video' ? t('productions.generateQuickFull') : t('productions.generateFilmFull')}</button>
      <button className={`${button} w-full`} disabled={!project.synopsis || !project.characters.length || Boolean(productionIssues.length) || Boolean(productionBusy) || !storyVideoConfigurationReady} onClick={() => stageFilm(false)}><ChevronRight size={13} /> {project.projectType === 'quick_video' ? t('productions.openDirector') : t('productions.openFilmDirector')}</button>
      <p className="text-[9px] text-text-muted">{t('productions.completeHint')}</p>
      {project.projectType === 'quick_video' && (
        <QuickVideoBatchPanel
          project={project}
          workspace={workspace}
          videoModel={filmVideoModel}
          imageModel={filmImageModel}
          resolution={storyVideoResolution}
          aspectRatio={storyVideoAspectRatio}
          durationSeconds={filmDuration}
        />
      )}
    </div>
  )
}
