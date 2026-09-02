import { useUiTranslation } from '../../i18n'
import { input } from './storyLabChrome'
import type { StoryProject, StoryWritingProvider } from './types'

export function StoryProviderWritingFields({
  project, provider, writingReady, onProviderChange, onPatchProvider,
}: {
  project: StoryProject
  provider: StoryWritingProvider
  writingReady: boolean
  onProviderChange: (value: StoryWritingProvider) => void
  onPatchProvider: (value: Partial<StoryProject['provider']>) => void
}) {
  const { t } = useUiTranslation('storyLab')
  return (
    <>
      <label className="block text-[10px] text-text-muted">{t('provider.writingLlm')}
        <select className={`${input} mt-1`} value={provider} onChange={event => onProviderChange(event.target.value as StoryWritingProvider)}>
          <option value="maestro">{t('provider.internalLlm')}</option>
          <option value="deepseek">DeepSeek</option>
          <option value="minimax">MiniMax</option>
          <option value="openai">OpenAI</option>
          <option value="openai-compatible">Custom OpenAI-compatible</option>
        </select>
      </label>
      <p className={`text-[10px] ${writingReady ? 'text-emerald-400' : 'text-amber-300'}`}>
        {writingReady ? t('provider.writingReady') : t('provider.writingMissing')}
      </p>
      {provider !== 'maestro' && (
        <label className="block text-[10px] text-text-muted">{t('provider.writingModel')}
          {provider === 'deepseek' ? (
            <select className={`${input} mt-1`} value={project.provider.writingModel || 'deepseek-v4-pro'} onChange={event => onPatchProvider({ writingModel: event.target.value })}>
              <option value="deepseek-v4-pro">DeepSeek V4 Pro</option>
              <option value="deepseek-v4-flash">DeepSeek V4 Flash</option>
            </select>
          ) : provider === 'minimax' ? (
            <select className={`${input} mt-1`} value={project.provider.writingModel || 'MiniMax-M3'} onChange={event => onPatchProvider({ writingModel: event.target.value })}>
              <option value="MiniMax-M3">MiniMax M3</option>
              <option value="MiniMax-M2.7">MiniMax M2.7</option>
              <option value="MiniMax-M2.7-highspeed">MiniMax M2.7 Highspeed</option>
            </select>
          ) : (
            <input className={`${input} mt-1`} value={project.provider.writingModel} onChange={event => onPatchProvider({ writingModel: event.target.value })} />
          )}
        </label>
      )}
    </>
  )
}
