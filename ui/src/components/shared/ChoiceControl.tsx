import { useFieldIds } from '../common/fieldIds'
import type { ChoiceConfig } from '../../types'

export function ChoiceControl({ config, value, onChange, label }: {
  config: ChoiceConfig
  value: string
  onChange: (val: string) => void
  label: string
}) {
  const fieldIds = useFieldIds()

  // Build items from either selection+labels or choices format
  const items: { label: string; value: string }[] = config.choices
    ? config.choices.map(([l, v]) => ({ label: l, value: v }))
    : (config.selection || []).map(val => ({
        value: val,
        label: config.labels?.[val] || val || 'Default',
      }))

  if (items.length === 0) return null

  return (
    <div>
      <label htmlFor={fieldIds('f0')} className="text-[11px] text-text-muted uppercase tracking-wider mb-1.5 block">
        {config.label || label}
      </label>
      <select aria-label={config.label || label} id={fieldIds('f0')}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full bg-bg-tertiary border border-border rounded-lg px-3 py-2 text-sm text-text-primary focus:outline-none focus:border-accent-blue"
      >
        {items.map(item => (
          <option key={item.value} value={item.value}>{item.label}</option>
        ))}
      </select>
    </div>
  )
}
