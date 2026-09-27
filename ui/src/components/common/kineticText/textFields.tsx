import type { ReactNode } from 'react'

export const fieldClass = 'mt-1 min-h-9 w-full rounded border border-border bg-bg-tertiary px-2 text-sm'
export const selectClass = 'ml-2 rounded border border-border bg-bg-tertiary p-2'

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return <label className="block text-xs text-text-secondary">{label}{children}</label>
}

export function NumberField({ label, value, step, onChange }: { label: string; value: number; step?: number; onChange: (value: number) => void }) {
  return <Field label={label}><input type="number" step={step ?? 1} value={value} onChange={event => { const next = event.target.valueAsNumber; if (Number.isFinite(next)) onChange(next) }} className={fieldClass} /></Field>
}

export function Choice({ label, value, options, onChange }: { label: string; value: string; options: { value: string; label: string }[]; onChange: (value: string) => void }) {
  return <Field label={label}><select value={value} onChange={event => onChange(event.target.value)} className={selectClass}>{options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></Field>
}
