import { Loader2, WandSparkles } from 'lucide-react'
import { isActiveSet, type AnimationSetJob } from '../../api/characterAnimationSets'
import { useUiTranslation } from '../../i18n'
import { animationDef, localized, missingSetSheets, type AnimationSetName } from '../../lib/characterAnimations'
import type { CharacterKit } from '../../lib/characterKit'

const small = 'inline-flex min-h-8 items-center gap-1 rounded-md border border-border px-2 text-[11px] disabled:opacity-40'
const BUTTONS = [
  { set: 'walk-directions', label: 'animations.sets.makeDirections' }, { set: 'walk-12', label: 'animations.sets.makeWalk12' },
  { set: 'idle-directions', label: 'animations.sets.makeIdle' },
] as const satisfies ReadonlyArray<{ set: AnimationSetName; label: string }>
const STOPPED = ['failed', 'cancelled', 'interrupted']

function SetProgress({ job, onCancel }: { job: AnimationSetJob; onCancel: (jobId: string) => void }) {
  const { t, i18n } = useUiTranslation('characters')
  const working = isActiveSet(job)
  return <div className="space-y-1" role="status" data-testid="animation-set-progress">
    <p className="text-[11px] text-text-secondary">
      {t(`animations.sets.job.${job.status}`)} · {t('animations.sets.progress', { done: job.done, total: job.total })}{job.error ? ` — ${job.error}` : ''}
      {working && job.status !== 'cancelling' && <button type="button" className={`${small} ml-2`} onClick={() => onCancel(job.jobId)}>{t('animations.cancel')}</button>}
    </p>
    {job.autoApproveNote && <p className="text-[11px] text-amber-200">{job.autoApproveNote}</p>}
    <ul className="space-y-0.5 text-[11px]">{job.sheets.map(sheet => {
      const def = animationDef(sheet.animationId)
      return <li key={sheet.animationId} className={sheet.status === 'failed' ? 'text-red-300' : 'text-text-muted'}>
        {def ? localized(def.title, i18n.language) : sheet.animationId}: {t(`animations.sets.sheet.${sheet.status}`)}
        {sheet.autoApproved ? ` · ${t('animations.sets.autoApproved')}` : ''}{sheet.failed?.length ? ` · ${t('animations.sets.failedChecks', { checks: sheet.failed.join(', ') })}` : ''}
        {sheet.error ? ` — ${sheet.error}` : ''}
      </li>
    })}</ul>
  </div>
}

/** «Crear andares completos»: the twelve-pose walk of the five directions (and the breaths) as one server job. It makes the sheets the
 * character lacks one after another; a stopped one is continued by pressing the button again. Each sheet is saved to review, as any other. */
export function AnimationSetBar({ kit, model, busy, latest, onStart, onCancel }: {
  kit: CharacterKit; model: string; busy: boolean; latest: Partial<Record<AnimationSetName, AnimationSetJob>>
  onStart: (set: AnimationSetName) => void; onCancel: (jobId: string) => void
}) {
  const { t } = useUiTranslation('characters')
  const shown = Object.values(latest).sort((a, b) => b!.createdAt - a!.createdAt)[0]
  return <section data-testid="animation-sets" className="space-y-2 rounded-lg border border-border bg-bg-secondary p-3">
    <h4 className="text-sm font-medium">{t('animations.sets.title')}</h4>
    <p className="text-[11px] text-text-muted">{t('animations.sets.intro')}</p>
    <div className="flex flex-wrap gap-2">{BUTTONS.map(({ set, label }) => {
      const missing = missingSetSheets(kit, set)
      const resumable = STOPPED.includes(latest[set]?.status ?? '') && missing > 0
      const working = latest[set] ? isActiveSet(latest[set]!) : false
      return <button key={set} type="button" data-testid={`make-set-${set}`} disabled={busy || !model || missing === 0} className={`${small} text-cyan-200`} onClick={() => onStart(set)}
        title={missing === 0 ? t('animations.sets.allMade') : t('animations.sets.missing', { count: missing })}>
        {working ? <Loader2 size={12} className="animate-spin" /> : <WandSparkles size={12} />}
        {resumable ? t('animations.sets.resume') : t(label)}</button>
    })}</div>
    {shown && <SetProgress job={shown} onCancel={onCancel} />}
  </section>
}
