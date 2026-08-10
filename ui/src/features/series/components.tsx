import type { ReactNode } from 'react'

export function SeriesField({
  label, required, hint, children,
}: { label: string; required?: boolean; hint?: string; children: ReactNode }) {
  return (
    <label className={`block rounded-xl border p-3 ${required ? 'border-violet-500/50 shadow-[0_0_18px_rgba(139,92,246,0.09)]' : 'border-border'}`}>
      <span className="mb-1.5 flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wide text-text-secondary">
        {label}{required && <span className="text-violet-400">• required</span>}
      </span>
      {children}
      {hint && <span className="mt-1.5 block text-[10px] leading-relaxed text-text-muted">{hint}</span>}
    </label>
  )
}

export function SectionCard({ title, description, action, children }: {
  title: string; description?: string; action?: ReactNode; children: ReactNode
}) {
  return (
    <section className="rounded-xl border border-border bg-bg-secondary p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-text-primary">{title}</h3>
          {description && <p className="mt-1 text-[11px] leading-relaxed text-text-muted">{description}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

export function Pill({ children, tone = 'neutral' }: {
  children: ReactNode; tone?: 'neutral' | 'green' | 'amber' | 'red' | 'violet' | 'blue'
}) {
  const tones = {
    neutral: 'border-border text-text-muted bg-bg-tertiary',
    green: 'border-green-500/30 text-green-300 bg-green-500/10',
    amber: 'border-amber-500/30 text-amber-300 bg-amber-500/10',
    red: 'border-red-500/30 text-red-300 bg-red-500/10',
    violet: 'border-violet-500/30 text-violet-300 bg-violet-500/10',
    blue: 'border-blue-500/30 text-blue-300 bg-blue-500/10',
  }
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] ${tones[tone]}`}>{children}</span>
}
