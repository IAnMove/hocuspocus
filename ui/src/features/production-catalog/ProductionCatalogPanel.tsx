import { useTranslation } from 'react-i18next'
import { LightCreate } from './LightCreate'
import { WorkRow } from './WorkRow'
import { FORMAT_KEYS, STATUS_KEYS, isFormat, isStatus, type CatalogPage, type LightFormat } from './types'

const FILTER_FORMATS = ['', ...Object.keys(FORMAT_KEYS)] as const
const FILTER_STATUSES = ['', ...Object.keys(STATUS_KEYS)] as const

export function ProductionCatalogPanel({
  workspace, page, format, status, onFormat, onStatus, onCreate, onClose,
}: {
  workspace: string
  page: CatalogPage
  format: string
  status: string
  onFormat: (value: string) => void
  onStatus: (value: string) => void
  onCreate: (body: { intent_id: string, format: LightFormat, title: string }) => void
  onClose: () => void
}) {
  const { t } = useTranslation('productionCatalog')
  return <div className="flex h-full min-h-0 w-full flex-col bg-bg-primary p-4 text-text-primary" role="dialog" aria-modal="true" aria-labelledby="production-catalog-title">
    <div className="mb-3 flex items-start justify-between gap-3">
      <div>
        <h2 id="production-catalog-title" className="text-lg">{t('title')}</h2>
        <p className="text-xs text-text-muted">{t('workspace', { workspace })}</p>
      </div>
      <button type="button" className="rounded border border-border px-2 py-1 text-xs" onClick={onClose}>{t('close')}</button>
    </div>
    <div className="mb-3 flex flex-wrap gap-2 text-xs">
      <label>
        {t('filters.format')}
        <select className="ml-1 rounded border border-border bg-bg-primary" data-filter="format" value={format} onChange={event => onFormat(event.target.value)}>
          {FILTER_FORMATS.map(item => <option key={item || 'all'} value={item}>{item && isFormat(item) ? t(FORMAT_KEYS[item]) : t('filters.all')}</option>)}
        </select>
      </label>
      <label>
        {t('filters.status')}
        <select className="ml-1 rounded border border-border bg-bg-primary" data-filter="status" value={status} onChange={event => onStatus(event.target.value)}>
          {FILTER_STATUSES.map(item => <option key={item || 'all'} value={item}>{item && isStatus(item) ? t(STATUS_KEYS[item]) : t('filters.all')}</option>)}
        </select>
      </label>
    </div>
    <LightCreate onCreate={onCreate} />
    {page.warnings.map(item => <p key={`${item.source}:${item.error}`} className="text-xs text-text-muted">{t('warning', { source: item.source, error: item.error })}</p>)}
    {page.works.length ? page.works.map(work => <WorkRow key={work.production_id} work={work} />) : <p className="text-xs text-text-muted">{t('empty')}</p>}
  </div>
}
