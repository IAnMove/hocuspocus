import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { estimateSource, kindProgress, produceTargets, readEstimate, waitingSteps } from './listModel'
import { useGameAssetsStore } from './store'
import { buttonClass, panelClass } from './styles'
import type { GameEstimate } from './types'

type Mode = 'pending' | 'rerender' | 'selected'

export function GameProducePanel() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const selectedIds = useGameAssetsStore(state => state.selectedIds)
  const job = useGameAssetsStore(state => state.produceJob)
  const previewList = useGameAssetsStore(state => state.previewList)
  const startProduce = useGameAssetsStore(state => state.startProduce)
  const cancelProduce = useGameAssetsStore(state => state.cancelProduce)
  const resumeProduce = useGameAssetsStore(state => state.resumeProduce)
  const setSection = useGameAssetsStore(state => state.setSection)
  const [pending, setPending] = useState<Mode | null>(null)
  const [estimate, setEstimate] = useState<GameEstimate | null>(null)
  const [note, setNote] = useState('')

  const ask = async (mode: Mode) => {
    const targets = produceTargets(game?.assets || [], mode, selectedIds)
    if (!targets.length) {
      setNote(t('nothingToProduce'))
      setPending(null)
      return
    }
    setNote('')
    const report = await previewList({
      items: targets.map(asset => ({ kind: asset.kind, id: asset.id, name: asset.name, description: asset.description, spec: asset.spec })),
    })
    setEstimate(readEstimate(report.estimate))
    setPending(mode)
  }

  const confirm = async () => {
    if (!pending || !game) return
    const targets = produceTargets(game.assets, pending, selectedIds)
    const assetIds = pending === 'pending' ? undefined : targets.map(asset => asset.id)
    const rerender = pending === 'rerender' || targets.some(asset => asset.status === 'stale')
    await startProduce({ assetIds, rerender })
    setPending(null)
  }

  const bars = kindProgress(job?.steps)
  const waiting = waitingSteps(job?.steps)
  const running = job?.steps?.find(step => step.status === 'running')
  const source = estimate ? estimateSource(estimate.source) : 'defaults'

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} onClick={() => { void ask('pending') }}>{t('producePending')}</button>
        <button type="button" className={buttonClass} onClick={() => { void ask('rerender') }}>{t('produceStale')}</button>
        <button type="button" className={buttonClass} onClick={() => { void ask('selected') }}>{t('produceSelected')}</button>
        {job && !['completed', 'failed', 'cancelled', 'canceled', 'interrupted'].includes(job.status) && (
          <button type="button" className={buttonClass} onClick={() => { void cancelProduce() }}>{t('cancelProduce')}</button>
        )}
      </div>
      {note && <p className="text-sm">{note}</p>}
      {job?.status === 'interrupted' && (
        <p className={`${panelClass} text-sm`}>
          {t('interrupted')}
          <button type="button" className={`${buttonClass} ml-2`} onClick={() => { void resumeProduce() }}>{t('resumeProduce')}</button>
        </p>
      )}
      {job && <p className="text-sm">{job.message || job.status}</p>}
      {running && <p className="text-sm">{t('currentStep', { name: running.assetId })}</p>}
      {bars.map(bar => (
        <div key={bar.kind}>
          <p className="text-sm">{bar.kind} {t('produceProgress', { done: bar.done, total: bar.total })}</p>
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
      {job?.steps?.some(step => step.error) && (
        <ul className="text-sm">
          {job.steps.filter(step => step.error).map(step => <li key={step.assetId}>{step.assetId}: {step.error}</li>)}
        </ul>
      )}
      {pending && estimate && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-label={t('confirmProduce')}>
          <div className={`${panelClass} w-full max-w-md space-y-2`}>
            <p>{t('estimate', { minutes: estimate.minutes })} · {source === 'history' ? t('sourceHistory') : source === 'trial' ? t('sourceTrial') : t('sourceDefaults')}</p>
            {Object.entries(estimate.byKind).map(([kind, minutes]) => <p key={kind} className="text-sm">{kind}: {minutes}</p>)}
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
