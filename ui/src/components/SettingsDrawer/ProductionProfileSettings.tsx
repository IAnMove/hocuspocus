import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { useStore, getFamiliesForMode } from '../../stores/useStore'
import {
  MINIMAX_IMAGE_MODELS,
  MINIMAX_MUSIC_MODELS,
  defaultImageModel,
  defaultModel3dModel,
  defaultTextBaseUrl,
  defaultTextModel,
  downloadedModelOptions,
  keepCurrentOption,
  listedTextModels,
  model3dProfileOptions,
  textModelOptions,
} from '../../lib/productionProfileCatalog'

function CatalogSelect({
  value, options, disabled, onChange, emptyLabel,
}: {
  value: string
  options: { id: string; label: string }[]
  disabled?: boolean
  onChange: (value: string) => void
  emptyLabel?: string
}) {
  const listed = keepCurrentOption(options, value)
  return (
    <select
      value={value}
      disabled={disabled || listed.length === 0}
      onChange={e => onChange(e.target.value)}
      className="mt-1 w-full min-w-0 flex-1 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
    >
      {listed.length === 0 && <option value="">{emptyLabel || '—'}</option>}
      {listed.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}
    </select>
  )
}

export function ProductionProfileSettings() {
  const { t } = useUiTranslation('settings')
  const savedProductionProfile = useStore(s => s.productionProfile)
  const productionProfileConfigured = useStore(s => s.productionProfileConfigured)
  const productionProfileLoading = useStore(s => s.productionProfileLoading)
  const updateProductionProfile = useStore(s => s.updateProductionProfile)
  const llmModels = useStore(s => s.llmModels)
  const loadLlmModels = useStore(s => s.loadLlmModels)
  const installedModels = useStore(s => s.models)
  const families = useStore(s => s.families)
  const [productionProfileDraft, setProductionProfile] = useState<typeof savedProductionProfile | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const productionProfile = productionProfileDraft ?? savedProductionProfile
  const imageFamilies = getFamiliesForMode('image', families).map(family => family.id)
  const videoFamilies = getFamiliesForMode('video', families).map(family => family.id)
  const model3dFamilies = getFamiliesForMode('model3d', families).map(family => family.id)
  const hunyuanOptions = downloadedModelOptions(installedModels, model3dFamilies)

  const loadRemoteTextModels = async () => {
    setRefreshing(true)
    try {
      const provider = productionProfile.text.provider
      await loadLlmModels({
        provider,
        url: productionProfile.text.base_url,
      })
      const listed = listedTextModels(useStore.getState().llmModels, provider)
      setProductionProfile(current => {
        const draft = current ?? savedProductionProfile
        if (listed.some(option => option.id === draft.text.model)) return draft
        return {
          ...draft,
          text: { ...draft.text, model: listed[0]?.id || '' },
        }
      })
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-border bg-bg-secondary/40 p-3">
      <div>
        <h3 className="text-[11px] text-text-secondary uppercase tracking-wider font-medium">
          {t('services.profileTitle')}
        </h3>
        <p className="text-[10px] text-text-muted mt-1">{t('services.profileHint')}</p>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-[10px] text-text-muted">
          {t('services.textProvider')}
          <select
            value={productionProfile.text.provider}
            onChange={e => {
              const provider = e.target.value as typeof productionProfile.text.provider
              const base_url = defaultTextBaseUrl(provider, productionProfile.text.base_url || '')
              setProductionProfile({
                ...productionProfile,
                text: {
                  ...productionProfile.text,
                  provider,
                  model: defaultTextModel(provider, productionProfile.text.model, llmModels),
                  base_url,
                },
              })
              if (provider === 'ollama' || provider === 'remote') {
                void loadLlmModels({ provider, url: base_url }).then(() => {
                  const listed = listedTextModels(useStore.getState().llmModels, provider)
                  setProductionProfile(current => {
                    const draft = current ?? savedProductionProfile
                    if (listed.some(option => option.id === draft.text.model)) return draft
                    return {
                      ...draft,
                      text: { ...draft.text, model: listed[0]?.id || '' },
                    }
                  })
                })
              }
            }}
            disabled={productionProfileLoading}
            className="mt-1 w-full bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
          >
            <option value="local">{t('services.providers.local')}</option>
            <option value="ollama">{t('services.providers.ollama')}</option>
            <option value="minimax">{t('services.providers.minimax')}</option>
            <option value="grok">{t('services.providers.grok')}</option>
            <option value="remote">{t('services.providers.remote')}</option>
            <option value="openai">{t('services.providers.openai')}</option>
            <option value="anthropic">{t('services.providers.anthropic')}</option>
            <option value="deepseek">{t('services.providers.deepseek')}</option>
          </select>
        </label>
        <label className="text-[10px] text-text-muted">
          {t('services.textModel')}
          <CatalogSelect
            value={productionProfile.text.model}
            options={textModelOptions(llmModels, productionProfile.text.provider, productionProfile.text.model)}
            disabled={productionProfileLoading}
            emptyLabel={t('services.noRemoteModels')}
            onChange={value => setProductionProfile({
              ...productionProfile,
              text: { ...productionProfile.text, model: value },
            })}
          />
        </label>
        {(productionProfile.text.provider === 'ollama' || productionProfile.text.provider === 'remote') && (
          <label className="col-span-2 text-[10px] text-text-muted">
            {t('services.textServerUrl')}
            <div className="mt-1 flex gap-1">
              <input
                value={productionProfile.text.base_url || ''}
                onChange={e => setProductionProfile({
                  ...productionProfile,
                  text: { ...productionProfile.text, base_url: e.target.value },
                })}
                placeholder="http://192.168.1.10:11434"
                disabled={productionProfileLoading}
                className="min-w-0 flex-1 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
              />
              <button
                type="button"
                disabled={productionProfileLoading || refreshing}
                onClick={() => void loadRemoteTextModels()}
                className="shrink-0 rounded-lg border border-border px-2 text-[10px] text-accent-blue disabled:opacity-50"
              >
                {refreshing ? t('services.loadingRemoteModels') : t('services.loadRemoteModels')}
              </button>
            </div>
          </label>
        )}
        <label className="text-[10px] text-text-muted">
          {t('services.imageProviderModel')}
          <div className="mt-1 flex gap-1">
            <select
              value={productionProfile.image.provider}
              onChange={e => {
                const provider = e.target.value as typeof productionProfile.image.provider
                const localOptions = downloadedModelOptions(installedModels, imageFamilies)
                setProductionProfile({
                  ...productionProfile,
                  image: {
                    ...productionProfile.image,
                    provider,
                    model: defaultImageModel(provider, localOptions, productionProfile.image.model),
                  },
                })
              }}
              disabled={productionProfileLoading}
              className="w-2/5 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
            >
              <option value="minimax">{t('services.providers.minimaxImage')}</option>
              <option value="local">{t('services.providers.localGeneric')}</option>
              <option value="maestro">{t('services.providers.maestro')}</option>
            </select>
            <CatalogSelect
              value={productionProfile.image.model}
              options={productionProfile.image.provider === 'minimax'
                ? MINIMAX_IMAGE_MODELS
                : downloadedModelOptions(installedModels, imageFamilies)}
              disabled={productionProfileLoading}
              onChange={value => setProductionProfile({
                ...productionProfile,
                image: { ...productionProfile.image, model: value },
              })}
            />
          </div>
        </label>
        <label className="text-[10px] text-text-muted">
          {t('services.musicProviderModel')}
          <div className="mt-1 flex gap-1">
            <select
              value={productionProfile.music.provider}
              onChange={e => setProductionProfile({
                ...productionProfile,
                music: {
                  ...productionProfile.music,
                  provider: e.target.value as typeof productionProfile.music.provider,
                  model: e.target.value === 'minimax' ? 'music-3.0' : 'ace_step_v1_5_xl_sft_lm_4b',
                },
              })}
              disabled={productionProfileLoading}
              className="w-2/5 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
            >
              <option value="local">{t('services.providers.aceLocal')}</option>
              <option value="minimax">{t('services.providers.minimaxMusic')}</option>
              <option value="maestro">{t('services.providers.maestro')}</option>
            </select>
            <CatalogSelect
              value={productionProfile.music.model}
              options={productionProfile.music.provider === 'minimax'
                ? MINIMAX_MUSIC_MODELS
                : downloadedModelOptions(installedModels, ['tts']).filter(option =>
                  option.id.startsWith('ace_step') || option.id.startsWith('heartmula') || option.id === 'minimax_music3')}
              disabled={productionProfileLoading}
              onChange={value => setProductionProfile({
                ...productionProfile,
                music: { ...productionProfile.music, model: value },
              })}
            />
          </div>
          {productionProfile.music.provider === 'minimax' && (
            <p className="mt-1 text-[10px] text-amber-300">{t('services.minimaxMusicWarn')}</p>
          )}
        </label>
        <label className="text-[10px] text-text-muted">
          {t('services.model3dProviderModel')}
          <div className="mt-1 flex gap-1">
            <select
              value={productionProfile.model3d?.provider || 'local'}
              onChange={e => {
                const provider = e.target.value as NonNullable<typeof productionProfile.model3d>['provider']
                setProductionProfile({
                  ...productionProfile,
                  model3d: {
                    ...(productionProfile.model3d || { provider: 'local', model: 'hunyuan3d-2mini-turbo' }),
                    provider,
                    model: defaultModel3dModel(provider),
                  },
                })
              }}
              disabled={productionProfileLoading}
              className="w-2/5 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
            >
              <option value="local">{t('services.providers.hunyuanLocal')}</option>
              <option value="meshy">{t('services.providers.meshy')}</option>
              <option value="hi3d">{t('services.providers.hi3d')}</option>
            </select>
            <CatalogSelect
              value={productionProfile.model3d?.model || 'hunyuan3d-2mini-turbo'}
              options={model3dProfileOptions(productionProfile.model3d?.provider || 'local', hunyuanOptions)}
              disabled={productionProfileLoading}
              onChange={value => setProductionProfile({
                ...productionProfile,
                model3d: {
                  ...(productionProfile.model3d || { provider: 'local', model: 'hunyuan3d-2mini-turbo' }),
                  model: value,
                },
              })}
            />
          </div>
        </label>
      </div>
      <label className="text-[10px] text-text-muted block">
        {t('services.videoModel')}
        <CatalogSelect
          value={productionProfile.video.model}
          options={downloadedModelOptions(installedModels, videoFamilies)}
          disabled={productionProfileLoading}
          onChange={value => setProductionProfile({
            ...productionProfile,
            video: { ...productionProfile.video, model: value },
          })}
        />
      </label>
      <div className="grid grid-cols-4 gap-2">
        <label className="text-[10px] text-text-muted">
          {t('services.resolution')}
          <select
            value={productionProfile.video.settings.resolution}
            onChange={e => setProductionProfile({
              ...productionProfile,
              video: { ...productionProfile.video, settings: { ...productionProfile.video.settings, resolution: e.target.value as typeof productionProfile.video.settings.resolution } },
            })}
            disabled={productionProfileLoading}
            className="mt-1 w-full bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
          >
            {['480p', '540p', '720p', '768p', '1080p'].map(value => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label className="text-[10px] text-text-muted">
          {t('services.canvas')}
          <select
            value={productionProfile.video.settings.aspectRatio}
            onChange={e => setProductionProfile({
              ...productionProfile,
              video: { ...productionProfile.video, settings: { ...productionProfile.video.settings, aspectRatio: e.target.value as typeof productionProfile.video.settings.aspectRatio } },
            })}
            disabled={productionProfileLoading}
            className="mt-1 w-full bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
          >
            {['16:9', '9:16', '1:1', '4:3', '3:4'].map(value => <option key={value}>{value}</option>)}
          </select>
        </label>
        <label className="text-[10px] text-text-muted">
          {t('services.steps')}
          <input
            type="number"
            value={productionProfile.video.settings.steps}
            onChange={e => setProductionProfile({
              ...productionProfile,
              video: { ...productionProfile.video, settings: { ...productionProfile.video.settings, steps: Number(e.target.value) } },
            })}
            disabled={productionProfileLoading}
            className="mt-1 w-full bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
          />
        </label>
        <label className="text-[10px] text-text-muted">
          {t('services.flowAudioShift')}
          <div className="mt-1 flex gap-1">
            <input
              type="number"
              value={productionProfile.video.settings.flowShift}
              onChange={e => setProductionProfile({
                ...productionProfile,
                video: { ...productionProfile.video, settings: { ...productionProfile.video.settings, flowShift: Number(e.target.value) } },
              })}
              disabled={productionProfileLoading}
              className="min-w-0 w-1/2 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
            />
            <input
              type="number"
              value={productionProfile.video.settings.audioShift}
              onChange={e => setProductionProfile({
                ...productionProfile,
                video: { ...productionProfile.video, settings: { ...productionProfile.video.settings, audioShift: Number(e.target.value) } },
              })}
              disabled={productionProfileLoading}
              className="min-w-0 w-1/2 bg-bg-tertiary border border-border rounded-lg px-2 py-1.5 text-xs text-text-primary"
            />
          </div>
        </label>
      </div>
      <p className="text-[10px] text-text-muted">
        {productionProfileConfigured ? t('services.profileSaved') : t('services.profileDefaults')}
        {' '}{t('services.profileSizeHint')}
      </p>
      <div className="flex justify-end">
        <button
          type="button"
          disabled={productionProfileLoading || !productionProfile.text.model || JSON.stringify(productionProfile) === JSON.stringify(savedProductionProfile)}
          onClick={() => void updateProductionProfile(productionProfile).then(() => setProductionProfile(null))}
          className="rounded-lg bg-accent-blue px-3 py-1.5 text-xs text-white disabled:opacity-40"
        >
          {productionProfileLoading ? t('services.saving') : t('services.saveProfile')}
        </button>
      </div>
    </div>
  )
}
