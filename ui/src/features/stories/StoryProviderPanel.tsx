import { getModelMode, useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import { button, panel } from './storyLabChrome'
import { resolveStoryWritingProvider } from './provider'
import { StoryProviderImageFields } from './StoryProviderImageFields'
import { StoryProviderWritingFields } from './StoryProviderWritingFields'
import type { StoryProject, StoryWritingProvider } from './types'

export function StoryProviderPanel({
  project, patch, onProfileModeChange,
}: {
  project: StoryProject
  patch: (patch: Partial<StoryProject>) => void
  onProfileModeChange: (useGlobalProfile: boolean) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const services = useStore(state => state.servicesConfig)
  const models = useStore(state => state.models)
  const profile = useStore(state => state.productionProfile)
  const resolvedWriting = resolveStoryWritingProvider(profile, project)
  const provider = resolvedWriting.provider
  const effectiveImageProvider = project.provider.useGlobalProfile && profile.image.provider === 'minimax'
    ? 'minimax' : project.provider.imageProvider
  const effectiveImageModel = project.provider.useGlobalProfile
    ? profile.image.model : project.provider.imageModel
  const installedImageModels = models.filter(model =>
    model.is_downloaded !== false
    && getModelMode(model.model_type, model.family) === 'image')
  const writingReady = provider === 'maestro'
    || (provider === 'deepseek' && Boolean(services?.deepseek_api_key_set))
    || (provider === 'minimax' && Boolean(services?.minimax_api_key_set))
    || (provider === 'openai' && Boolean(services?.openai_api_key_set))
    || (provider === 'openai-compatible'
      && Boolean(services?.compatible_api_key_set && services?.compatible_base_url))
  const imageReady = effectiveImageProvider === 'maestro'
    ? installedImageModels.some(model => model.model_type === effectiveImageModel)
    : Boolean(services?.minimax_api_key_set)
  const setProvider = (next: StoryWritingProvider) => {
    const defaults = next === 'deepseek'
      ? { writingModel: 'deepseek-v4-pro', writingBaseUrl: 'https://api.deepseek.com' }
      : next === 'minimax'
        ? { writingModel: 'MiniMax-M3', writingBaseUrl: 'https://api.minimax.io/v1' }
        : next === 'openai'
          ? { writingModel: 'gpt-4.1', writingBaseUrl: 'https://api.openai.com' }
          : next === 'openai-compatible'
            ? { writingModel: '', writingBaseUrl: services?.compatible_base_url || '' }
            : { writingModel: project.provider.writingModel, writingBaseUrl: project.provider.writingBaseUrl }
    patch({ provider: { ...project.provider, writingProvider: next, ...defaults } })
  }
  const patchProvider = (value: Partial<StoryProject['provider']>) =>
    patch({ provider: { ...project.provider, ...value } })
  return (
    <div className={`${panel} space-y-3`}>
      <div>
        <h3 className="text-sm font-semibold text-text-primary">{t('provider.title')}</h3>
        <p className="text-[10px] text-text-muted mt-1">{t('provider.hint')}</p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <button type="button" className={`${button} ${project.provider.useGlobalProfile ? 'border-accent-blue text-accent-blue' : ''}`}
          onClick={() => onProfileModeChange(true)}>{t('provider.useGlobal')}</button>
        <button type="button" className={`${button} ${!project.provider.useGlobalProfile ? 'border-accent-blue text-accent-blue' : ''}`}
          onClick={() => onProfileModeChange(false)}>{t('provider.override')}</button>
      </div>
      {project.provider.useGlobalProfile && (
        <p className="text-[10px] text-emerald-300">
          {t('provider.globalLine', {
            writing: `${resolvedWriting.provider} / ${resolvedWriting.model}${resolvedWriting.baseUrl ? ` · ${resolvedWriting.baseUrl}` : ''}`,
            image: `${profile.image.provider} / ${profile.image.model}`,
            video: profile.video.model,
            resolution: profile.video.settings.resolution,
            aspect: profile.video.settings.aspectRatio,
          })}
        </p>
      )}
      <fieldset disabled={project.provider.useGlobalProfile} className="space-y-3 disabled:opacity-50">
        <StoryProviderWritingFields
          project={project}
          provider={provider}
          writingReady={writingReady}
          onProviderChange={setProvider}
          onPatchProvider={patchProvider}
        />
        <StoryProviderImageFields
          project={project}
          imageReady={imageReady}
          installedImageModels={installedImageModels}
          onPatchProvider={patchProvider}
        />
      </fieldset>
    </div>
  )
}
