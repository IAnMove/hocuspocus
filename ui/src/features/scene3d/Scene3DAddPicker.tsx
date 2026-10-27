import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useUiTranslation } from '../../i18n'
import {
  addPickerCatalog,
  filterAddPickerItems,
  type AddPickerCategory,
  type AddPickerItem,
} from './addPickerCatalog'

const CATEGORIES: AddPickerCategory[] = ['all', 'world', 'overlay', 'demo', 'text', 'prop']

export function Scene3DAddPicker({ open, disabled, props, initialCategory = 'all', onPick, onClose }: {
  open: boolean
  disabled?: boolean
  props?: ReactNode
  initialCategory?: AddPickerCategory
  onPick: (item: AddPickerItem) => void
  onClose: () => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const { t: fx } = useUiTranslation('sceneFx')
  const { t: text } = useUiTranslation('kineticText')
  const [category, setCategory] = useState<AddPickerCategory>(initialCategory)
  const [query, setQuery] = useState('')
  const items = useMemo(() => addPickerCatalog(), [])
  useEffect(() => {
    if (!open) return
    setCategory(initialCategory)
    setQuery('')
  }, [open, initialCategory])
  if (!open) return null
  const labelOf = (item: AddPickerItem) => item.labelNs === 'kineticText'
    ? text(item.labelKey as 'title', { defaultValue: item.id })
    : fx(item.labelKey as 'title', { defaultValue: item.id })
  const visible = category === 'prop' ? [] : filterAddPickerItems(items, category, query, labelOf)
  return (
    <div role="dialog" aria-modal="true" aria-label={t('addPicker.title')} data-testid="scene3d-add-picker" className="fixed inset-0 z-[200] flex items-start justify-center bg-black/60 p-4">
      <div className="flex max-h-[min(40rem,80vh)] w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-border bg-bg-secondary shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-border px-3 py-2">
          <h2 className="text-sm font-semibold text-text-primary">{t('addPicker.title')}</h2>
          <button type="button" onClick={onClose} className="min-h-10 rounded-lg border border-border px-3 text-xs text-text-primary">{t('addPicker.close')}</button>
        </div>
        <label className="block px-3 pt-3 text-xs text-text-muted">
          {t('addPicker.search')}
          <input
            value={query}
            aria-label={t('addPicker.search')}
            placeholder={t('addPicker.searchHelp')}
            onChange={event => setQuery(event.target.value)}
            className="mt-1 min-h-10 w-full rounded-lg border border-border bg-bg-primary px-3 text-sm text-text-primary"
          />
        </label>
        <div className="flex flex-wrap gap-2 px-3 py-2" role="tablist" aria-label={t('addPicker.title')}>
          {CATEGORIES.map(id => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={category === id}
              data-testid={`scene3d-add-category-${id}`}
              onClick={() => setCategory(id)}
              className={`min-h-9 rounded-full border px-3 text-xs ${category === id ? 'border-cyan-300 bg-cyan-300/15 text-cyan-50' : 'border-border text-text-secondary'}`}
            >
              {t(`addPicker.category.${id}`)}
            </button>
          ))}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-3" data-testid="scene3d-add-list">
          {category === 'prop' ? props : (
            <ul className="grid grid-cols-2 gap-2 sm:grid-cols-3">
              {visible.map(item => (
                <li key={item.id}>
                  <button
                    type="button"
                    disabled={disabled}
                    data-testid={`scene3d-add-item-${item.id}`}
                    onClick={() => onPick(item)}
                    className="min-h-11 w-full rounded-lg border border-border bg-bg-primary px-2 text-left text-xs text-text-primary disabled:opacity-40"
                  >
                    {labelOf(item)}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {category !== 'prop' && visible.length === 0 && <p className="text-xs text-text-muted">{t('addPicker.empty')}</p>}
        </div>
      </div>
    </div>
  )
}
