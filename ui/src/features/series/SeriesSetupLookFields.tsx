import type { TFunction } from 'i18next'
import { useUiTranslation } from '../../i18n'
import { SeriesField } from './components'
import { finishChoice, finishOptions, finishValue } from './shotLook'
import { selectClass, textareaClass } from './styles'
import type { SeriesProject } from './types'

type Patch = (value: Partial<SeriesProject>) => void

/** The series' own episode shape (series_library.EPISODE_FORMAT_LIMIT characters). Empty shows the default that
 * agents follow without one; an empty value is sent so the stored one is cleared. */
export function SeriesEpisodeFormatField({ series, t, patch }: { series: SeriesProject; t: TFunction<'seriesLab'>; patch: Patch }) {
  return (
    <SeriesField label={t('setup.episodeFormat')} hint={t('setup.episodeFormatHint')}>
      <textarea className={textareaClass} maxLength={2000} value={series.episodeFormat || ''} placeholder={t('setup.episodeFormatDefault')}
        onChange={event => patch({ episodeFormat: event.target.value })} />
    </SeriesField>
  )
}

/** The finish over every 2D shot (series_finish.py). Paper is the default, so choosing it clears `look.finish`. */
export function SeriesFinishField({ series, t, patch }: { series: SeriesProject; t: TFunction<'seriesLab'>; patch: Patch }) {
  const { t: names } = useUiTranslation('kineticText')
  const current = finishValue(series.look?.finish) || 'paper'
  const choose = (value: string) => {
    const choice = finishChoice(value)
    if (choice === undefined) return
    const rest = { ...series.look }
    delete rest.finish
    patch({ look: choice === 'paper' ? rest : { ...rest, finish: choice } })
  }
  return (
    <SeriesField label={t('setup.finish')} hint={t('setup.finishHint')}>
      <select className={selectClass} value={current} onChange={event => choose(event.target.value)}>
        {finishOptions(t, names, current).map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </SeriesField>
  )
}
