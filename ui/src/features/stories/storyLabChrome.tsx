import { Check, Loader2, Sparkles } from 'lucide-react'
import type { StoryGenerationScope } from './types'

export const button = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-border bg-bg-tertiary px-2.5 py-1.5 text-xs text-text-secondary hover:text-text-primary hover:bg-bg-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors'
export const input = 'w-full rounded-md border border-border bg-bg-tertiary px-2 py-1.5 text-xs text-text-primary focus:outline-none focus:border-accent-blue'
export const panel = 'rounded-xl border border-border bg-bg-secondary p-3 md:p-4'
export const requiredInput = 'border-violet-400/70 bg-violet-500/5 shadow-[0_0_14px_rgba(139,92,246,0.22)] focus:border-violet-300 focus:shadow-[0_0_18px_rgba(139,92,246,0.32)]'

export function Field({
  label, value, onChange, rows = 1, placeholder = '', required = false,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  rows?: number
  placeholder?: string
  required?: boolean
}) {
  const requiredClass = required ? requiredInput : ''
  return (
    <label className={`block text-[10px] ${required ? 'text-violet-200' : 'text-text-muted'}`}>
      {label}{required && <span className="ml-1 text-violet-300" title="Required">●</span>}
      {rows > 1
        ? <textarea className={`${input} ${requiredClass} mt-1`} rows={rows} value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} required={required} aria-required={required} />
        : <input className={`${input} ${requiredClass} mt-1`} value={value} onChange={event => onChange(event.target.value)} placeholder={placeholder} required={required} aria-required={required} />}
    </label>
  )
}

export function SectionHeader({
  title, description, scope, busy, approved, instruction, setInstruction, onGenerate, onApprove,
}: {
  title: string
  description: string
  scope: StoryGenerationScope
  busy: StoryGenerationScope | null
  approved: boolean
  instruction: string
  setInstruction: (value: string) => void
  onGenerate: (scope: StoryGenerationScope) => void
  onApprove: () => void
}) {
  return (
    <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-3 mb-4">
      <div>
        <h2 className="text-lg font-semibold text-text-primary">{title}</h2>
        <p className="text-xs text-text-muted mt-1">{description}</p>
      </div>
      <div className="lg:max-w-[680px]">
        <div className="flex flex-col sm:flex-row gap-2">
          <input className={`${input} sm:w-72`} value={instruction} onChange={event => setInstruction(event.target.value)} placeholder="Optional regeneration instruction…" />
          <button className={button} disabled={Boolean(busy)} onClick={() => onGenerate(scope)}
            title="Uses the LLM to generate or rewrite this section's text. It does not generate images.">
            {busy === scope ? <Loader2 size={13} className="animate-spin" /> : <Sparkles size={13} />} Generate text
          </button>
          <button className={`${button} ${approved ? 'border-emerald-500 text-emerald-400' : ''}`} onClick={onApprove}
            title="Confirms the current version of this section. It does not generate content.">
            <Check size={13} /> {approved ? 'Approved' : 'Approve'}
          </button>
        </div>
        <p className="mt-1.5 text-[9px] leading-relaxed text-text-muted">
          LLM text only: generates or rewrites this section's fields and preserves existing image references; it does not render images. Guided mode lets you review the draft before applying it. Approve only confirms the current version.
        </p>
      </div>
    </div>
  )
}
