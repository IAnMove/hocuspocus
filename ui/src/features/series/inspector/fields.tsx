import { useId, type ReactNode } from 'react'
import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { useUiTranslation } from '../../../i18n'
import { inputClass, secondaryButton, selectClass } from '../styles'

/** Small labelled inputs for the inspector's inline editors: large enough to tap on a phone, compact on a desk. */
const label = 'block min-w-0 text-[10px] font-medium text-text-muted'
const control = `${inputClass} mt-0.5 min-h-10 sm:min-h-0 sm:py-1.5`

export function NumberInput({ title, value, onChange, min, max, step = 0.05, placeholder }: {
  title: string; value: unknown; onChange: (value: number | undefined) => void; min?: number; max?: number; step?: number; placeholder?: string
}) {
  const shown = typeof value === 'number' && Number.isFinite(value) ? value : ''
  return <label className={label}>{title}
    <input className={control} type="number" inputMode="decimal" min={min} max={max} step={step} value={shown} placeholder={placeholder}
      onChange={event => {
        if (event.target.value === '') { onChange(undefined); return }
        const next = Number(event.target.value)
        if (Number.isFinite(next)) onChange(min !== undefined || max !== undefined ? Math.min(max ?? next, Math.max(min ?? next, next)) : next)
      }} />
  </label>
}

export function TextInput({ title, value, onChange, placeholder, multiline }: {
  title: string; value: unknown; onChange: (value: string) => void; placeholder?: string; multiline?: boolean
}) {
  const text = typeof value === 'string' ? value : ''
  return <label className={label}>{title}
    {multiline
      ? <textarea className={`${control} min-h-16 resize-y text-sm sm:text-xs`} value={text} placeholder={placeholder} onChange={event => onChange(event.target.value)} />
      : <input className={control} value={text} placeholder={placeholder} onChange={event => onChange(event.target.value)} />}
  </label>
}

export function SelectInput({ title, value, onChange, options, empty }: {
  title: string; value: unknown; onChange: (value: string) => void
  options: Array<{ value: string; label: string }>; empty?: string
}) {
  const current = value === undefined || value === null ? '' : String(value)
  const known = options.some(option => option.value === current)
  return <label className={label}>{title}
    <select className={`${selectClass} mt-0.5 min-h-10 sm:min-h-0 sm:py-1.5`} value={current} onChange={event => onChange(event.target.value)}>
      {empty !== undefined && <option value="">{empty}</option>}
      {current && !known && <option value={current}>{current}</option>}
      {options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  </label>
}

/** A workspace file by name, with the workspace's files of that kind as suggestions. */
export function FileInput({ title, value, onChange, files }: { title: string; value: unknown; onChange: (value: string) => void; files: string[] }) {
  const id = useId()
  return <label className={label}>{title}
    <input className={`${control} font-mono`} list={id} value={typeof value === 'string' ? value : ''} spellCheck={false}
      onChange={event => onChange(event.target.value.trim())} />
    <datalist id={id}>{files.map(name => <option key={name} value={name} />)}</datalist>
  </label>
}

export function CheckInput({ title, value, onChange }: { title: string; value: unknown; onChange: (value: boolean) => void }) {
  return <label className="flex min-h-10 items-center gap-2 text-[11px] text-text-secondary sm:min-h-0">
    <input type="checkbox" className="h-4 w-4" checked={value === true} onChange={event => onChange(event.target.checked)} />{title}
  </label>
}


/** A list of items, each edited by `render`, with move, remove and add. */
export function ListEditor<T>({ items, onChange, render, create, addLabel, max = 12, itemLabel }: {
  items: T[]; onChange: (items: T[]) => void; render: (item: T, change: (item: T) => void, index: number) => ReactNode
  create: () => T; addLabel: string; max?: number; itemLabel: (index: number) => string
}) {
  const { t } = useUiTranslation('seriesLab')
  const move = (from: number, to: number) => {
    const next = [...items]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item!)
    onChange(next)
  }
  const small = `${secondaryButton} min-h-10 min-w-10 px-2 sm:min-h-0 sm:min-w-0 sm:py-1`
  return <div className="space-y-2">
    {items.map((item, index) => <fieldset key={index} className="min-w-0 rounded-lg border border-border bg-bg-primary p-2">
      <legend className="sr-only">{itemLabel(index)}</legend>
      <div className="mb-1 flex items-center gap-1">
        <span className="mr-auto text-[10px] font-semibold text-text-secondary">{itemLabel(index)}</span>
        <button type="button" className={small} disabled={index === 0} aria-label={t('inspector.list.up', { item: itemLabel(index) })}
          onClick={() => move(index, index - 1)}><ArrowUp size={12} /></button>
        <button type="button" className={small} disabled={index === items.length - 1} aria-label={t('inspector.list.down', { item: itemLabel(index) })}
          onClick={() => move(index, index + 1)}><ArrowDown size={12} /></button>
        <button type="button" className={small} aria-label={t('inspector.list.remove', { item: itemLabel(index) })}
          onClick={() => onChange(items.filter((_value, position) => position !== index))}><Trash2 size={12} /></button>
      </div>
      {render(item, next => onChange(items.map((value, position) => position === index ? next : value)), index)}
    </fieldset>)}
    <button type="button" className={`${secondaryButton} min-h-10 sm:min-h-0`} disabled={items.length >= max} onClick={() => onChange([...items, create()])}>
      <Plus size={13} />{addLabel}</button>
  </div>
}
