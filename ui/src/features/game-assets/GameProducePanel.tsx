import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { codeLabel } from './gameErrors'
import { EstimateSummary } from './gameUi'
import { kindProgress, produceItems, produceTargets, readEstimate, waitingSteps } from './listModel'
import { useGameAssetsStore } from './store'
import { canResumeJob, hasWaitingSteps, isActiveJob } from './storeModel'
import { buttonClass, errorClass, panelClass } from './styles'
import type { GameEstimate, ProduceJob } from './types'

type Mode = 'pending' | 'rerender' | 'selected'
const MODES: { mode: Mode; label: 'producePending' | 'produceStale' | 'produceSelected' }[] = [
  { mode: 'pending', label: 'producePending' },
  { mode: 'rerender', label: 'produceStale' },
  { mode: 'selected', label: 'produceSelected' },
]

export function GameProducePanel() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const selectedIds = useGameAssetsStore(state => state.selectedIds)
  const job = useGameAssetsStore(state => state.produceJob)
  const previewList = useGameAssetsStore(state => state.previewList)
  const startProduce = useGameAssetsStore(state => state.startProduce)
  const [pending, setPending] = useState<{ mode: Mode; estimate: GameEstimate } | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const active = isActiveJob(job)

  const ask = async (mode: Mode) => {
    const targets = produceTargets(game?.assets || [], mode, selectedIds)
    setPending(null)
    if (!targets.length) {
      setNote(t('nothingToProduce'))
      return
    }
    setNote('')
    setBusy(true)
    const outcome = await previewList({ items: produceItems(targets) })
    setBusy(false)
    if (outcome.ok) setPending({ mode, estimate: readEstimate(outcome.report.estimate) })
    else setNote(outcome.error)
  }

  const confirm = async () => {
    if (!pending || !game) return
    const targets = produceTargets(game.assets, pending.mode, selectedIds)
    const assetIds = pending.mode === 'pending' ? undefined : targets.map(asset => asset.id)
    const rerender = pending.mode === 'rerender' || targets.some(asset => asset.status === 'stale')
    setPending(null)
    setBusy(true)
    await startProduce({ assetIds, rerender })
    setBusy(false)
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {MODES.map(item => (
          <button key={item.mode} type="button" className={buttonClass} disabled={active || busy} onClick={() => { void ask(item.mode) }}>{t(item.label)}</button>
        ))}
        <CancelButton job={job} />
      </div>
      {active && <p className="text-sm">{t('alreadyRunningHint')}</p>}
      {note && <p className={errorClass} role="alert">{note}</p>}
      <ResumeNotice job={job} />
      {job && <JobProgress job={job} />}
      {pending && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-label={t('confirmProduce')}>
          <div className={`${panelClass} w-full max-w-md space-y-2`}>
            <EstimateSummary estimate={pending.estimate} />
            <div className="flex gap-2">
              <button type="button" className={buttonClass} onClick={() => { void confirm() }}>{t('confirmProduce')}</button>
              <button type="button" className={buttonClass} onClick={() => setPending(null)}>{t('close')}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/** Cancel while the job runs; a job already cancelling shows a disabled button. */
function CancelButton({ job }: { job: ProduceJob | null }) {
  const { t } = useUiTranslation('gameAssets')
  const cancelProduce = useGameAssetsStore(state => state.cancelProduce)
  if (!job || !isActiveJob(job)) return null
  if (job.status === 'cancelling') return <button type="button" className={buttonClass} disabled>{t('cancellingProduce')}</button>
  return <button type="button" className={buttonClass} onClick={() => { void cancelProduce() }}>{t('cancelProduce')}</button>
}

function resumeReason(job: ProduceJob): 'interrupted' | 'cancelledJob' | 'failedJob' | 'waitingResume' {
  if (job.status === 'interrupted') return 'interrupted'
  if (job.status === 'cancelled') return 'cancelledJob'
  if (job.status === 'failed') return 'failedJob'
  return 'waitingResume'
}

function ResumeNotice({ job }: { job: ProduceJob | null }) {
  const { t } = useUiTranslation('gameAssets')
  const resumeProduce = useGameAssetsStore(state => state.resumeProduce)
  const [busy, setBusy] = useState(false)
  if (!job || !canResumeJob(job)) return null
  const resume = async () => {
    setBusy(true)
    await resumeProduce()
    setBusy(false)
  }
  return (
    <p className={`${panelClass} text-sm`}>
      {t(resumeReason(job))}
      {job.status === 'completed' && hasWaitingSteps(job) && <span> {t('waitingResumeHint')}</span>}
      <button type="button" className={`${buttonClass} ml-2`} disabled={busy} onClick={() => { void resume() }}>{t('resumeProduce')}</button>
    </p>
  )
}

function JobProgress({ job }: { job: ProduceJob }) {
  const { t } = useUiTranslation('gameAssets')
  const setSection = useGameAssetsStore(state => state.setSection)
  const bars = kindProgress(job.steps)
  const waiting = waitingSteps(job.steps)
  const running = job.steps?.find(step => step.status === 'running')
  const failed = (job.steps || []).filter(step => step.error)
  return (
    <div className="space-y-3" aria-live="polite">
      <p className="text-sm">{t('jobStatus', { status: codeLabel('jobStatuses', job.status) })}</p>
      {running && <p className="text-sm">{t('currentStep', { name: running.assetId })}</p>}
      {bars.map(bar => (
        <div key={bar.kind}>
          <p className="text-sm">{codeLabel('kinds', bar.kind)} {t('produceProgress', { done: bar.done, total: bar.total })}{bar.waiting ? ` · ${t('waitingCount', { count: bar.waiting })}` : ''}</p>
          <div className="h-2 rounded bg-muted"><div className="h-2 rounded bg-emerald-600" style={{ width: `${bar.total ? (bar.done / bar.total) * 100 : 0}%` }} /></div>
        </div>
      ))}
      {waiting.length > 0 && (
        <div className={panelClass}>
          <p className="text-sm">{t('waitingDependency')}</p>
          {waiting.map(step => <p key={step.assetId} className="text-sm">{step.assetId}</p>)}
          <button type="button" className={buttonClass} onClick={() => setSection('review')}>{t('openReview')}</button>
        </div>
      )}
      {failed.length > 0 && (
        <ul className="text-sm">
          {failed.map(step => <li key={step.assetId}>{step.assetId}: {step.error}</li>)}
        </ul>
      )}
    </div>
  )
}
