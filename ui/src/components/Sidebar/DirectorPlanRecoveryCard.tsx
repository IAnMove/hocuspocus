import { AlertTriangle, Loader2, RotateCcw } from 'lucide-react'
import type { DirectorV2PlanJob } from '../../types'
import { useUiTranslation } from '../../i18n'

function formatTokenCount(value: number, language: string): string {
  return new Intl.NumberFormat(language === 'es' ? 'es-ES' : 'en-US').format(value)
}

function formatIndexRanges(indices: number[], emptyLabel: string): string {
  const sorted = [...new Set(indices)].sort((left, right) => left - right)
  if (sorted.length === 0) return emptyLabel
  const ranges: string[] = []
  let start = sorted[0]
  let end = sorted[0]
  for (const index of sorted.slice(1)) {
    if (index === end + 1) {
      end = index
      continue
    }
    ranges.push(start === end ? `${start}` : `${start}–${end}`)
    start = index
    end = index
  }
  ranges.push(start === end ? `${start}` : `${start}–${end}`)
  return ranges.join(', ')
}

export interface DirectorPlanRecoveryCardProps {
  job: DirectorV2PlanJob
  loading: boolean
  onResume: () => void
}

export function DirectorPlanRecoveryCard({ job, loading, onResume }: DirectorPlanRecoveryCardProps) {
  const { t, i18n } = useUiTranslation('director')
  const completed = job.completedIndices.length
  const tokenTotal = job.usage.total_tokens
  const hasMissingClips = job.missingIndices.length > 0
  return (
    <section
      aria-labelledby="director-plan-recovery-title"
      className="rounded-lg border border-amber-400/30 bg-amber-400/10 p-3 space-y-2"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle size={14} className="mt-0.5 shrink-0 text-amber-300" aria-hidden="true" />
        <div className="min-w-0">
          <h3 id="director-plan-recovery-title" className="text-xs font-semibold text-amber-100">
            {t('planRecovery.title')}
          </h3>
          <p className="mt-0.5 text-[11px] text-text-secondary">
            {t('planRecovery.body', { completed, total: job.total })}
          </p>
        </div>
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-[10px]">
        <dt className="text-text-muted">{t('planRecovery.missing')}</dt>
        <dd className="text-text-primary break-words">
          {hasMissingClips
            ? t('planRecovery.clips', { ranges: formatIndexRanges(job.missingIndices, t('planRecovery.none')) })
            : t('planRecovery.finishProposal')}
        </dd>
        <dt className="text-text-muted">{t('planRecovery.calls')}</dt>
        <dd className="text-text-primary">{job.calls}</dd>
        {typeof tokenTotal === 'number' && (
          <>
            <dt className="text-text-muted">{t('planRecovery.tokens')}</dt>
            <dd className="text-text-primary">{formatTokenCount(tokenTotal, i18n.language)}</dd>
          </>
        )}
      </dl>
      {job.error && <p className="text-[10px] text-amber-100/80 break-words">{job.error}</p>}
      <button
        type="button"
        onClick={onResume}
        disabled={loading}
        className="inline-flex min-h-9 w-full items-center justify-center gap-1.5 rounded-md border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-[11px] font-medium text-amber-100 transition-colors hover:bg-amber-300/20 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {loading ? <Loader2 size={12} className="animate-spin" aria-hidden="true" /> : <RotateCcw size={12} aria-hidden="true" />}
        {loading
          ? t('planRecovery.resuming')
          : hasMissingClips
            ? t('planRecovery.resumeMissing')
            : t('planRecovery.resumeProposal')}
      </button>
    </section>
  )
}
