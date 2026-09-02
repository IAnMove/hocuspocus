import { Download, Loader2, Palette } from 'lucide-react'
import { MINIMAX_IMAGE_API_MODEL } from '../../lib/externalModels'
import { useUiTranslation } from '../../i18n'
import { button, input, panel } from './storyLabChrome'
import type { ModelDef } from '../../types'

export function StoryAssetsStyleConverter({
  styleConversion, setStyleConversion, styleConversionModel, setStyleConversionModel,
  styleConversionBusy, styleModelDownloading, setStyleModelDownloadError, styleModelDownloadError,
  localStyleModels, qwenModel, fluxModel, styleAssetIds, styleUsesMiniMax, selectedStyleModel,
  styleModelReady, miniMaxIncompatibleSelection, installStyleConversionModel, cancelStyleConversion,
  convertSelectedAssetsToStyle,
}: {
  styleConversion: string
  setStyleConversion: (value: string) => void
  styleConversionModel: string
  setStyleConversionModel: (value: string) => void
  styleConversionBusy: boolean
  styleModelDownloading: string
  setStyleModelDownloadError: (value: string) => void
  styleModelDownloadError: string
  localStyleModels: ModelDef[]
  qwenModel: string
  fluxModel: string
  styleAssetIds: string[]
  styleUsesMiniMax: boolean
  selectedStyleModel?: ModelDef
  styleModelReady: boolean
  miniMaxIncompatibleSelection: boolean
  installStyleConversionModel: () => void
  cancelStyleConversion: () => void
  convertSelectedAssetsToStyle: () => void
}) {
  const { t } = useUiTranslation('storyLab')
  const engine = styleUsesMiniMax
    ? t('assets.engineMinimax')
    : selectedStyleModel?.is_downloaded
      ? t('assets.engineLocalReady', { name: selectedStyleModel?.name || styleConversionModel })
      : t('assets.engineLocalInstall', { name: selectedStyleModel?.name || styleConversionModel })
  const selectedLabel = styleAssetIds.length === 1
    ? t('assets.selectedOne', { count: styleAssetIds.length, engine })
    : t('assets.selectedMany', { count: styleAssetIds.length, engine })
  return (
    <section className={`${panel} mb-5 border-violet-500/30 bg-violet-500/5`}>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div>
          <h3 className="text-sm font-semibold text-violet-100">{t('assets.styleTitle')}</h3>
          <p className="mt-1 text-[10px] leading-relaxed text-text-muted">{t('assets.styleHint')}</p>
          <textarea
            className={`${input} mt-3 min-h-24 resize-y`}
            value={styleConversion}
            onChange={event => setStyleConversion(event.target.value)}
            placeholder={t('assets.stylePlaceholder')}
            aria-label={t('assets.styleAria')}
          />
          {/photoreal|photo-real|fotorreal/i.test(styleConversion) && (
            <p className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-[9px] leading-relaxed text-amber-200">
              {t('assets.photorealWarn')}
            </p>
          )}
        </div>
        <div className="flex flex-col justify-end gap-2">
          <label className="block text-[10px] text-text-muted">{t('assets.styleModel')}
            <select
              className={`${input} mt-1`}
              value={styleConversionModel}
              disabled={styleConversionBusy || Boolean(styleModelDownloading)}
              onChange={event => {
                setStyleConversionModel(event.target.value)
                setStyleModelDownloadError('')
              }}
            >
              <optgroup label={t('assets.externalApi')}>
                <option value={MINIMAX_IMAGE_API_MODEL}>{t('assets.minimaxCharacters')}</option>
              </optgroup>
              <optgroup label={t('assets.localEditing')}>
                {localStyleModels.map(model => (
                  <option key={model.model_type} value={model.model_type}>
                    {model.name}{model.model_type === qwenModel ? t('assets.strictPreservation') : model.model_type === fluxModel ? t('assets.fastFourStep') : ''}{model.is_downloaded ? t('assets.installed') : t('assets.notInstalled')}
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
          <div className="rounded-md border border-border bg-bg-primary/40 p-2 text-[10px] text-text-muted">
            {selectedLabel}
          </div>
          {!styleUsesMiniMax && !styleModelReady && !styleModelDownloading && (
            <button className={`${button} border-sky-500/60 text-sky-200`} onClick={() => void installStyleConversionModel()}>
              <Download size={13} /> {t('assets.installEditor')}
            </button>
          )}
          {styleModelDownloading && (
            <div className="rounded-md border border-sky-500/40 bg-sky-500/5 p-2 text-[10px] text-sky-200">
              <Loader2 size={12} className="mr-1 inline animate-spin" /> {t('assets.downloading')}
            </div>
          )}
          {styleModelDownloadError && <p className="text-[9px] text-red-300">{styleModelDownloadError}</p>}
          {miniMaxIncompatibleSelection && (
            <p className="rounded-md border border-amber-500/40 bg-amber-500/5 p-2 text-[9px] leading-relaxed text-amber-200">
              {t('assets.minimaxIncompatible')}
            </p>
          )}
          {styleConversionBusy ? (
            <button className={`${button} border-amber-500/60 text-amber-200`} onClick={cancelStyleConversion}>
              <Loader2 size={13} className="animate-spin" /> {t('assets.stopAfterCurrent')}
            </button>
          ) : (
            <button
              className={`${button} border-violet-400/60 text-violet-200`}
              disabled={!styleAssetIds.length || !styleConversion.trim() || !styleModelReady || miniMaxIncompatibleSelection || Boolean(styleModelDownloading)}
              onClick={() => void convertSelectedAssetsToStyle()}
            >
              <Palette size={13} /> {t('assets.convertSelected')}
            </button>
          )}
          <p className="text-[9px] leading-relaxed text-text-muted">{t('assets.styleEngineHint')}</p>
        </div>
      </div>
    </section>
  )
}
