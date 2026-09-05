import { useUiTranslation } from '../../i18n'
import { input } from './storyLabChrome'
import type { StoryProject } from './types'
import type { ModelDef } from '../../types'

export function StoryProviderImageFields({
  project, imageReady, installedImageModels, onPatchProvider,
}: {
  project: StoryProject
  imageReady: boolean
  installedImageModels: ModelDef[]
  onPatchProvider: (value: Partial<StoryProject['provider']>) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const usesMiniMaxImage = project.provider.imageProvider === 'minimax'
  const status = imageReady
    ? (usesMiniMaxImage ? t('provider.minimaxImageReady') : t('provider.localImageReady'))
    : (usesMiniMaxImage ? t('provider.minimaxImageMissing') : t('provider.chooseLocalImage'))
  return (
    <>
      <label className="block text-[10px] text-text-muted">{t('provider.imageProvider')}
        <select className={`${input} mt-1`} value={project.provider.imageProvider} onChange={event => onPatchProvider({ imageProvider: event.target.value as 'maestro' | 'minimax' })}>
          <option value="maestro">{t('provider.imageLocal')}</option>
          <option value="minimax">{t('provider.imageMinimax')}</option>
        </select>
      </label>
      {project.provider.imageProvider === 'maestro' && (
        <label className="block text-[10px] text-text-muted">{t('provider.imageModel')}
          <select
            className={`${input} mt-1`}
            value={project.provider.imageModel}
            onChange={event => onPatchProvider({ imageModel: event.target.value })}
          >
            {!installedImageModels.some(model => model.model_type === project.provider.imageModel)
              && <option value={project.provider.imageModel}>{t('provider.imageUnavailable', { model: project.provider.imageModel || t('provider.selectInstalled') })}</option>}
            {installedImageModels.map(model => (
              <option key={model.model_type} value={model.model_type}>{model.name}</option>
            ))}
          </select>
        </label>
      )}
      <p className={`text-[10px] ${imageReady ? 'text-emerald-400' : 'text-amber-300'}`}>{status}</p>
    </>
  )
}
