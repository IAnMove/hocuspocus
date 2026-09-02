import { MINIMAX_IMAGE_API_LABEL, MINIMAX_IMAGE_API_MODEL } from '../../lib/externalModels'
import { useUiTranslation } from '../../i18n'
import { input } from './storyLabChrome'
import { StoryVideoFormatControls } from './StoryVideoFormatControls'
import type { StoryProductionsTabProps } from './storyLabProductions'
import type { StoryWritingProvider } from './types'

export function StoryMusicProductionModels(props: StoryProductionsTabProps & { ready: boolean; writerLabel: string; videoLabel: string }) {
  const { t } = useUiTranslation('storyLab')
  const {
    project, patchMusicWritingProvider, setMusicWritingProvider, directMusicVideo, directReferenceVideo,
    filmImageModel, filmVideoModel, selectableImageModels, selectableVideoModels, selectedFilmImageModel,
    selectedFilmVideoModel, selectDirectorImageModel, selectStoryVideoModel, storyVideoOptionsReady,
    storyVideoResolution, storyVideoAspectRatio, storyVideoOptions, storyVideoAdjusted, setStoryVideoFormat,
    ready, writerLabel, videoLabel, approvedVisualReferenceCount, musicWritingReady, directVideoMasterReady,
    directReferenceVideoReady, directReferenceVideoSupported,
  } = props
  return (
    <div className="rounded-lg border border-border bg-bg-tertiary/40 p-2.5 space-y-2">
      <div>
        <p className="text-[10px] font-medium text-text-secondary">{t('productions.generationModels')}</p>
        <p className="mt-0.5 text-[9px] text-text-muted">{t('productions.generationModelsHint')}</p>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        <label className="block text-[10px] text-text-muted">{t('productions.planningLlm')}
          <select className={`${input} mt-1`} value={project.provider.writingProvider}
            onChange={event => setMusicWritingProvider(event.target.value as StoryWritingProvider)}>
            <option value="maestro">{t('productions.internalLlm')}</option>
            <option value="deepseek">DeepSeek</option>
            <option value="minimax">MiniMax</option>
            <option value="openai">OpenAI</option>
            <option value="openai-compatible">Custom OpenAI-compatible</option>
          </select>
        </label>
        {project.provider.writingProvider !== 'maestro' && (
          <label className="block text-[10px] text-text-muted">{t('productions.llmModel')}
            {project.provider.writingProvider === 'deepseek' ? (
              <select className={`${input} mt-1`} value={project.provider.writingModel || 'deepseek-v4-pro'} onChange={event => patchMusicWritingProvider({ writingModel: event.target.value })}>
                <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
                <option value="deepseek-v4-flash">DeepSeek V4 Flash</option>
              </select>
            ) : project.provider.writingProvider === 'minimax' ? (
              <select className={`${input} mt-1`} value={project.provider.writingModel || 'MiniMax-M3'} onChange={event => patchMusicWritingProvider({ writingModel: event.target.value })}>
                <option value="MiniMax-M3">MiniMax M3</option>
                <option value="MiniMax-M2.7">MiniMax M2.7</option>
                <option value="MiniMax-M2.7-highspeed">MiniMax M2.7 Highspeed</option>
              </select>
            ) : (
              <input className={`${input} mt-1`} value={project.provider.writingModel} onChange={event => patchMusicWritingProvider({ writingModel: event.target.value })} />
            )}
          </label>
        )}
        {directMusicVideo || directReferenceVideo ? (
          <div className="rounded-md border border-fuchsia-500/25 bg-fuchsia-500/5 px-2 py-1.5 text-[10px] text-text-muted">
            <span className="block font-medium text-fuchsia-200">{t('productions.imageUnused')}</span>
            <span className="mt-1 block text-[9px]">{directReferenceVideo ? t('productions.imageUnusedRefs') : t('productions.imageUnusedT2v')}</span>
          </div>
        ) : (
          <label className="block text-[10px] text-text-muted">{t('trailer.imageModel')}
            <select className={`${input} mt-1`} value={filmImageModel} onChange={event => selectDirectorImageModel(event.target.value)}>
              {filmImageModel !== MINIMAX_IMAGE_API_MODEL && !selectableImageModels.some(model => model.model_type === filmImageModel) && (
                <option value={filmImageModel}>{selectedFilmImageModel?.name || filmImageModel}</option>
              )}
              <optgroup label={t('productions.externalApi')}>
                <option value={MINIMAX_IMAGE_API_MODEL}>{MINIMAX_IMAGE_API_LABEL}</option>
              </optgroup>
              <optgroup label={t('productions.localModels')}>
                {selectableImageModels.map(model => (
                  <option key={model.model_type} value={model.model_type}>{model.name}</option>
                ))}
              </optgroup>
            </select>
          </label>
        )}
        <label className="block text-[10px] text-text-muted">{t('trailer.videoModel')}
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
                ? t('productions.inheritedStoryOnly')
                : filmVideoModel === 'minimax_h3_legacy'
                  ? t('productions.h3LegacyMusic')
                  : filmVideoModel.startsWith('ltx2')
                    ? t('productions.ltxGemma')
                    : t('productions.h3SavedStory')}
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
      </div>
      {project.provider.writingProvider === 'openai-compatible' && (
        <label className="block text-[10px] text-text-muted">{t('productions.compatibleBaseUrl')}
          <input className={`${input} mt-1`} value={project.provider.writingBaseUrl} onChange={event => patchMusicWritingProvider({ writingBaseUrl: event.target.value })} placeholder="https://…/v1" />
        </label>
      )}
      <p className={`text-[9px] ${ready ? 'text-text-muted' : 'text-amber-300'}`}>
        {ready
          ? directMusicVideo
            ? t('productions.readyT2v', { writer: writerLabel, video: videoLabel })
            : directReferenceVideo
              ? t('productions.readyRefs', { writer: writerLabel, count: approvedVisualReferenceCount, video: videoLabel })
              : t('productions.readyImages', { writer: writerLabel, image: selectedFilmImageModel?.name || filmImageModel, video: videoLabel })
          : !musicWritingReady
            ? t('productions.configurePlanningLlm')
            : !directVideoMasterReady
              ? t('productions.defineMaster')
              : !directReferenceVideoReady
                ? directReferenceVideoSupported
                  ? t('productions.approveLibrary')
                  : t('productions.directRefsNeedH3')
                : t('productions.configureMinimaxImage')}
      </p>
    </div>
  )
}
