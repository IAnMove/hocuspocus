import type { TFunction } from 'i18next'
import {
  h3FramesModelId,
  h3FusedStepRange,
  SERIES_SETUP_VIDEO_MODELS,
  seriesSetupVideoUnavailableReason,
  seriesStepsForVideoModel,
} from '../../lib/h3Catalog'
import { SeriesField } from './components'
import { inputClass, selectClass } from './styles'
import type { SeriesProject } from './types'
import {
  DEFAULT_SERIES_VIDEO_RESOLUTION, SERIES_VIDEO_RESOLUTION_LABELS, SERIES_VIDEO_RESOLUTIONS, seriesVideoResolution,
} from './videoResolution'

/** The H3 size of the script's video shots: the series' own choice, outside the provider settings, so a series that
 * follows the global profile still makes it. A shot's own size overrides it. */
export function SeriesVideoShotResolutionField({ series, t, patch }: {
  series: SeriesProject
  t: TFunction<'seriesLab'>
  patch: (value: Partial<SeriesProject>) => void
}) {
  return (
    <SeriesField label={t('providers.videoShotResolution')} hint={t('providers.videoShotResolutionHint')}>
      <select className={selectClass} value={series.videoShotResolution || DEFAULT_SERIES_VIDEO_RESOLUTION}
        onChange={event => patch({ videoShotResolution: seriesVideoResolution(event.target.value) })}>
        {SERIES_VIDEO_RESOLUTIONS.map(value => <option key={value} value={value}>{t(SERIES_VIDEO_RESOLUTION_LABELS[value])}</option>)}
      </select>
    </SeriesField>
  )
}

export function SeriesSetupVideoFields({
  series, t, patchProvider, patchVideo,
}: {
  series: SeriesProject
  t: TFunction<'seriesLab'>
  patchProvider: (value: Partial<SeriesProject['provider']>) => void
  patchVideo: (value: Partial<SeriesProject['provider']['videoSettings']>) => void
}) {
  const setupVideoModel = h3FramesModelId(series.provider.videoModel)
  const fusedSteps = h3FusedStepRange(series.provider.videoModel)
  const unknownVideo = seriesSetupVideoUnavailableReason(series.provider.videoModel)
  const selected = SERIES_SETUP_VIDEO_MODELS.some(item => item.id === setupVideoModel)
    ? setupVideoModel
    : series.provider.videoModel
  return (
    <>
      <SeriesField label={t('providers.videoModel')} hint={t('providers.videoModelHint')}>
        <select
          className={selectClass}
          value={selected}
          onChange={event => {
            const value = event.target.value
            patchProvider({
              videoModel: value,
              videoSettings: {
                ...series.provider.videoSettings,
                numInferenceSteps: seriesStepsForVideoModel(
                  value,
                  Number(series.provider.videoSettings.numInferenceSteps || 20),
                ),
              },
            })
          }}
        >
          {unknownVideo && <option value={series.provider.videoModel}>{series.provider.videoModel}</option>}
          {SERIES_SETUP_VIDEO_MODELS.map(item => (
            <option key={item.id} value={item.id}>{t(item.labelKey)}</option>
          ))}
        </select>
        {unknownVideo && <p className="mt-1 text-[10px] text-amber-300">{t('providers.unknownModel')}</p>}
      </SeriesField>
      <SeriesField label={t('providers.resolution')} hint={t('providers.resolutionHint')}>
        <select className={selectClass} value={String(series.provider.videoSettings.resolution || DEFAULT_SERIES_VIDEO_RESOLUTION)} onChange={event => patchVideo({ resolution: event.target.value })}>
          {SERIES_VIDEO_RESOLUTIONS.map(value => <option key={value} value={value}>{t(SERIES_VIDEO_RESOLUTION_LABELS[value])}</option>)}
        </select>
      </SeriesField>
      <SeriesField label={t('providers.orientation')}>
        <select className={selectClass} value={String(series.provider.videoSettings.orientation || 'landscape')} onChange={event => patchVideo({ orientation: event.target.value as 'landscape' | 'portrait' })}>
          <option value="landscape">{t('providers.landscape')}</option>
          <option value="portrait">{t('providers.portrait')}</option>
        </select>
      </SeriesField>
      <SeriesField label={t('providers.steps')} hint={fusedSteps ? t('providers.fusedStepsHint') : undefined}>
        <input
          className={inputClass}
          type="number"
          min={fusedSteps?.min || 1}
          max={fusedSteps?.max || 50}
          value={Number(series.provider.videoSettings.numInferenceSteps || (fusedSteps?.fallback || 20))}
          onChange={event => patchVideo({ numInferenceSteps: Number(event.target.value) })}
        />
      </SeriesField>
    </>
  )
}
