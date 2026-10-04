import { useEffect, useState } from 'react'
import { fetchSeriesTemplates, type SeriesTemplateCard } from '../../api/series'
import { useUiTranslation } from '../../i18n'
import { useSeriesStore } from './store'
import { secondaryButton } from './styles'

/** Start a series from a template: cast, locations, canon and a 2D pilot, in Spanish or English. */
export function SeriesTemplatePicker({ disabled, onCreate }: { disabled?: boolean; onCreate: (task: () => Promise<void>) => void }) {
  const { t, i18n } = useUiTranslation('seriesLab')
  const create = useSeriesStore(state => state.newSeriesFromTemplate)
  const [language, setLanguage] = useState<'es' | 'en'>(i18n.resolvedLanguage?.startsWith('es') ? 'es' : 'en')
  const [templates, setTemplates] = useState<SeriesTemplateCard[]>([]), [error, setError] = useState('')
  useEffect(() => {
    let alive = true
    fetchSeriesTemplates(language).then(next => { if (alive) { setTemplates(next); setError('') } })
      .catch(cause => { if (alive) setError((cause as Error).message) })
    return () => { alive = false }
  }, [language])
  return <details className="rounded-lg border border-border p-2 text-left" data-testid="series-template-picker">
    <summary className="cursor-pointer text-[11px] font-semibold">{t('templates.title')}</summary>
    <label className="mt-2 block text-[10px] text-text-muted">{t('templates.language')}
      <select className="ml-1 rounded border border-border bg-bg-primary px-1" value={language} onChange={event => setLanguage(event.target.value as 'es' | 'en')}>
        <option value="es">{t('languages.names.spanish')}</option>
        <option value="en">{t('languages.names.english')}</option>
      </select></label>
    <ul className="mt-2 space-y-2">{templates.map(item => <li key={item.id} className="rounded border border-border p-2">
      <p className="text-[11px] font-semibold">{item.title}</p>
      <p className="text-[10px] text-text-muted">{item.description}</p>
      <p className="text-[10px] text-text-muted">{t('templates.contents', { characters: item.characters.join(', '), shots: item.pilotShots })}</p>
      <button className={`mt-1 ${secondaryButton}`} disabled={disabled} onClick={() => onCreate(() => create(item.id, language))}>{t('templates.create', { title: item.title })}</button>
    </li>)}</ul>
    {error && <p role="alert" className="text-[10px] text-red-300">{error}</p>}
  </details>
}
