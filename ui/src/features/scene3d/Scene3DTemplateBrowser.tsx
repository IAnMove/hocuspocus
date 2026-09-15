import { useState } from 'react'
import { Search } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { campaignCard } from './campaignTemplates'
import { actionCard } from './actionTemplates'
import { SCENE3D_TEMPLATES, type Scene3DTemplateCategory, type Scene3DTemplateId } from './templates'
import { filterScene3DTemplates, settingsIn, type TemplateSetting } from './templateFilters'
import { Scene3DTemplateThumb } from './Scene3DTemplateThumb'

const categories = ['action', 'cinema', 'drive', 'space', 'music', 'product'] as const

export function Scene3DTemplateBrowser({ selected, disabled, onSelect }: {
  selected?: Scene3DTemplateId; disabled: boolean; onSelect: (id: Scene3DTemplateId) => void
}) {
  const { t, i18n } = useUiTranslation('scene3dEditor')
  const [category, setCategory] = useState<'all' | Scene3DTemplateCategory>('all')
  const [setting, setSetting] = useState<'all' | TemplateSetting>('all')
  const [query, setQuery] = useState('')
  const locale = i18n.language.startsWith('es') ? 'es' : 'en'
  const titleOf = (id: Scene3DTemplateId) => `${t(`template.${id}.title`)} ${t(`template.${id}.description`)}`
  const templates = filterScene3DTemplates({ category, setting, query, locale, titleOf })
  const settingChoices = settingsIn(filterScene3DTemplates({ category, setting: 'all', query, locale, titleOf }))
  return <section className="rounded-xl border border-border bg-bg-secondary p-3" aria-label={t('templates')}>
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-sm font-semibold text-text-primary">{t('templates')}
        <span className="ml-1 text-text-muted">{t('filterCount', { shown: templates.length, total: SCENE3D_TEMPLATES.length })}</span>
      </h2>
      <label className="flex min-h-10 items-center gap-2 rounded-lg border border-border bg-bg-primary px-3 text-text-muted"><Search size={16} />
        <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder={t('search')} aria-label={t('search')} className="min-w-0 bg-transparent text-sm text-text-primary outline-none" />
      </label>
    </div>
    <div className="my-2 flex flex-wrap gap-2" role="group" aria-label={t('filterCategory')}>
      {(['all', ...categories] as const).map(item => <button key={item} type="button" onClick={() => { setCategory(item); setSetting('all') }} aria-pressed={category === item}
        className={`min-h-9 rounded-lg border px-3 text-xs font-medium ${category === item ? 'border-cyan-300 bg-cyan-300/15 text-cyan-100' : 'border-border text-text-secondary hover:bg-bg-hover'}`}>
        {item === 'all' ? t('all') : t(`category.${item}`)}
      </button>)}
    </div>
    {settingChoices.length > 1 && <div className="mb-2 flex flex-wrap gap-2" role="group" aria-label={t('filterSetting')}>
      {(['all', ...settingChoices] as const).map(item => <button key={item} type="button" onClick={() => setSetting(item)} aria-pressed={setting === item}
        className={`min-h-8 rounded-full border px-2.5 text-[11px] font-medium ${setting === item ? 'border-amber-300 bg-amber-300/15 text-amber-100' : 'border-border text-text-muted hover:bg-bg-hover'}`}>
        {item === 'all' ? t('allSettings') : t(`setting.${item}`)}
      </button>)}
    </div>}
    <div className="grid max-h-[28rem] grid-cols-1 gap-2 overflow-y-auto p-1 sm:grid-cols-2 xl:grid-cols-3">
      {templates.map(item => {
        const card = campaignCard(item.id, locale) ?? actionCard(item.id, locale)
        return <button key={item.id} type="button" disabled={disabled} onClick={() => onSelect(item.id)} aria-pressed={selected === item.id}
          data-testid={`world3d-template-${item.id}`}
          className={`overflow-hidden rounded-lg border text-left transition-colors focus-visible:outline-2 focus-visible:outline-cyan-200 disabled:opacity-40 ${selected === item.id ? 'border-cyan-300 bg-cyan-300/10' : 'border-border bg-bg-primary hover:border-cyan-300/50'}`}>
          <Scene3DTemplateThumb id={item.id} />
          <span className="flex items-start justify-between gap-2 px-3 pt-2 text-sm font-semibold text-text-primary">{t(`template.${item.id}.title`)}<span className="whitespace-nowrap text-xs font-normal tabular-nums text-text-muted">{item.duration} s</span></span>
          <span className="mt-0.5 block px-3 pb-2 text-[11px] leading-4 text-text-secondary">{t(`template.${item.id}.description`)}</span>
          {selected === item.id && card?.requirements.map(req => <span key={req} className="block px-3 pb-1 text-[10px] leading-4 text-text-muted">{req}</span>)}
        </button>
      })}
    </div>
    {templates.length === 0 && <p role="status" className="p-4 text-sm text-text-secondary">{t('noResults')}</p>}
  </section>
}
