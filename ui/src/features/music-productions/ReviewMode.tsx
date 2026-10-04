import { useEffect, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { musicProductionFileUrl } from './fileUrl'
import type { MusicProductionShot, ReviewPlan } from './types'

const buttonClass = 'inline-flex items-center gap-1 rounded border border-border px-2 py-1 text-[11px] hover:bg-bg-hover disabled:opacity-50'

type ReviewStatus = 'pending' | 'approved' | 'changes_requested'

function reviewStatus(shot: MusicProductionShot): ReviewStatus {
  const status = shot.review?.status
  if (status === 'approved' || status === 'changes_requested' || status === 'pending') return status
  return 'pending'
}

function isPending(shot: MusicProductionShot): boolean {
  return reviewStatus(shot) !== 'approved'
}

function typingTarget(target: EventTarget | null): boolean {
  if (!target || !('tagName' in target)) return false
  const tag = String((target as { tagName?: string }).tagName || '')
  return tag === 'TEXTAREA' || tag === 'INPUT'
}

function isPlanPromise(value: ReviewPlan | Promise<ReviewPlan | void>): value is Promise<ReviewPlan | void> {
  return typeof (value as { then?: unknown }).then === 'function'
}

function storePlan(value: ReviewPlan | void | Promise<ReviewPlan | void>, setPlan: (plan: ReviewPlan) => void) {
  if (!value) return
  if (isPlanPromise(value)) {
    void value.then(plan => { if (plan) setPlan(plan) })
    return
  }
  setPlan(value)
}

export function ReviewMode({
  workspace, shots, busy, onClose, onApprove, onRequest, onApply, onOpenScene, onUseTake, onUndo, onLock,
}: {
  workspace: string
  shots: MusicProductionShot[]
  busy?: boolean
  onClose: () => void
  onApprove: (shot: string) => void
  onRequest: (shot: string, instruction: string) => ReviewPlan | void | Promise<ReviewPlan | void>
  onApply: (shot: string, instruction: string, plan: ReviewPlan) => void
  onOpenScene: (sceneName: string) => void
  onUseTake: (shot: string, takeFile: string) => void
  onUndo: (shot: string) => void
  onLock: (shot: string, locked: boolean) => void
}) {
  const { t } = useUiTranslation('navigation')
  const [pendingOnly, setPendingOnly] = useState(false)
  const [cursor, setCursor] = useState(0)
  const [instruction, setInstruction] = useState('')
  const [plan, setPlan] = useState<ReviewPlan | null>(null)
  const visible = pendingOnly ? shots.filter(isPending) : shots
  const index = visible.length === 0 ? 0 : Math.min(cursor, visible.length - 1)
  const shot = visible[index]
  const approved = shots.filter(item => reviewStatus(item) === 'approved').length

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (busy || typingTarget(event.target)) return
      if (event.key === 'ArrowRight' || event.key === 'j' || event.key === 'J') setCursor(index + 1)
      else if (event.key === 'ArrowLeft' || event.key === 'k' || event.key === 'K') setCursor(Math.max(0, index - 1))
      else if (event.key === 'Enter' && !plan && shot) onApprove(shot.key)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, index, onApprove, plan, shot])

  const ask = () => {
    if (!shot || !instruction.trim()) return
    storePlan(onRequest(shot.key, instruction.trim()), setPlan)
  }

  return <div role="dialog" aria-modal="true" aria-label={t('musicProductions.reviewTitle')} className="fixed inset-0 z-[120] flex flex-col bg-bg-primary">
    <header className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
      <h2 className="text-sm font-medium text-text-primary">{t('musicProductions.reviewTitle')}</h2>
      <p className="text-[11px] text-text-secondary">{t('musicProductions.progress', { approved, total: shots.length })}</p>
      <button type="button" className={buttonClass} aria-pressed={pendingOnly} onClick={() => { setPendingOnly(value => !value); setCursor(0); setPlan(null) }}>
        {pendingOnly ? t('musicProductions.allShots') : t('musicProductions.pendingOnly')}
      </button>
      <button type="button" className={buttonClass} onClick={onClose}>{t('musicProductions.closeReview')}</button>
    </header>
    {shot ? <ReviewShot
      workspace={workspace}
      shot={shot}
      busy={busy}
      instruction={instruction}
      plan={plan}
      onInstruction={value => { setInstruction(value); setPlan(null) }}
      onApprove={() => onApprove(shot.key)}
      onAsk={ask}
      onApply={() => { if (plan) { onApply(shot.key, instruction.trim(), plan); setPlan(null) } }}
      onOpenScene={onOpenScene}
      onUseTake={onUseTake}
      onUndo={() => onUndo(shot.key)}
      onLock={onLock}
    /> : <p className="p-4 text-xs text-text-secondary">{t('musicProductions.noPending')}</p>}
  </div>
}

function ReviewShot({
  workspace, shot, busy, instruction, plan, onInstruction, onApprove, onAsk, onApply, onOpenScene, onUseTake, onUndo, onLock,
}: {
  workspace: string
  shot: MusicProductionShot
  busy?: boolean
  instruction: string
  plan: ReviewPlan | null
  onInstruction: (value: string) => void
  onApprove: () => void
  onAsk: () => void
  onApply: () => void
  onOpenScene: (sceneName: string) => void
  onUseTake: (shot: string, takeFile: string) => void
  onUndo: () => void
  onLock: (shot: string, locked: boolean) => void
}) {
  const { t } = useUiTranslation('navigation')
  const status = reviewStatus(shot)
  const statusLabel = status === 'approved'
    ? t('musicProductions.statusApproved')
    : status === 'changes_requested'
      ? t('musicProductions.statusChanges')
      : t('musicProductions.statusPending')
  const video = musicProductionFileUrl(workspace, shot.scene_video)
  const locked = shot.review?.locked === true
  return <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-4">
    <h3 className="text-sm font-medium text-text-primary">{shot.key}</h3>
    <p className="text-[11px] text-text-secondary">{statusLabel}{locked ? ` · ${t('musicProductions.locked')}` : ''}</p>
    {video ? <video src={video} controls aria-label={t('musicProductions.sceneVideo')} className="max-h-[50vh] w-full rounded bg-black" /> : null}
    <p className="text-xs text-text-primary">{shot.lyric}</p>
    <p className="text-[11px] text-text-secondary">{t('musicProductions.framePrompt')}: {shot.frame_prompt || '—'}</p>
    <p className="text-[11px] text-text-secondary">{t('musicProductions.action')}: {shot.action || '—'}</p>
    <div className="flex flex-wrap gap-1">
      <button type="button" className={buttonClass} disabled={busy} onClick={onApprove}>{t('musicProductions.approve')}</button>
      <button type="button" className={buttonClass} disabled={busy || !shot.scene_doc} onClick={() => shot.scene_doc && onOpenScene(shot.scene_doc)}>
        {t('musicProductions.openScene')}
      </button>
      <button type="button" className={buttonClass} disabled={busy || locked || !shot.review?.history_id} onClick={onUndo}>{t('musicProductions.undo')}</button>
      <button type="button" className={buttonClass} disabled={busy} onClick={() => onLock(shot.key, !locked)}>
        {locked ? t('musicProductions.unlock') : t('musicProductions.lock')}
      </button>
    </div>
    <TakeList shot={shot} busy={busy} onUseTake={onUseTake} />
    <label className="flex flex-col gap-1 text-[11px] text-text-secondary" htmlFor="shot-review-note">
      {t('musicProductions.instruction')}
      <textarea id="shot-review-note" className="rounded border border-border bg-bg-secondary p-2 text-xs text-text-primary" value={instruction} onChange={event => onInstruction(event.target.value)} />
    </label>
    <button type="button" className={buttonClass} disabled={busy || !instruction.trim()} onClick={onAsk}>{t('musicProductions.requestChange')}</button>
    {plan ? <PlanDiff plan={plan} busy={busy} onApply={onApply} /> : null}
  </div>
}

function TakeList({ shot, busy, onUseTake }: { shot: MusicProductionShot; busy?: boolean; onUseTake: (shot: string, takeFile: string) => void }) {
  const { t } = useUiTranslation('navigation')
  const takes = shot.takes || []
  if (takes.length === 0) return null
  return <div className="flex flex-col gap-1">
    <span className="text-[11px] text-text-secondary">{t('musicProductions.otherTake')}</span>
    {takes.map(take => <button key={take.file} type="button" className={buttonClass} disabled={busy} onClick={() => onUseTake(shot.key, take.file)}>
      {t('musicProductions.useTake')} {take.file}
    </button>)}
  </div>
}

function PlanDiff({ plan, busy, onApply }: { plan: ReviewPlan; busy?: boolean; onApply: () => void }) {
  const { t } = useUiTranslation('navigation')
  const cost = plan.cost_estimate
  return <section aria-label={t('musicProductions.diff')} className="flex flex-col gap-2 rounded border border-border p-3">
    <h4 className="text-[11px] font-medium text-text-primary">{t('musicProductions.planSummary')}</h4>
    <p className="text-xs text-text-primary">{plan.plan?.summary || ''}</p>
    <pre className="overflow-auto text-[11px] text-text-secondary">{JSON.stringify(plan.diff || [], null, 2)}</pre>
    <p className="text-[11px] text-text-secondary">{t('musicProductions.cost')}: {cost?.image_jobs ?? 0} / {cost?.clip_jobs ?? 0} / {cost?.scene_exports ?? 0}</p>
    <button type="button" className={buttonClass} disabled={busy} onClick={onApply}>{t('musicProductions.applyPlan')}</button>
  </section>
}
