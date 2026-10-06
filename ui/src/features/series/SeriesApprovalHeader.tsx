import { CheckCheck, Film, Loader2, RotateCcw, Smile, Square } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { Pill } from './components'
import { greenButton, primaryButton, secondaryButton } from './styles'
import { PRODUCTION_MODES, type CastMember, type EpisodeStep, type ReviewFilter, type ReviewSummary } from './reviewModel'
import type { ApprovalRender } from './useApprovalRender'
import type { SeriesProductionMode } from './types'

const RENDER_ACTIONS: Partial<Record<EpisodeStep, 'approval.actions.render' | 'approval.actions.render_previews' | 'approval.actions.render_final'>> = {
  render: 'approval.actions.render', render_previews: 'approval.actions.render_previews', render_final: 'approval.actions.render_final',
}
const big = 'min-h-10 sm:min-h-0'

function Progress({ label, done, total }: { label: string; done: number; total: number }) {
  const percent = total ? Math.round(done * 100 / total) : 0
  return <div className="min-w-[9rem] flex-1">
    <div className="flex justify-between text-[10px] text-text-secondary"><span>{label}</span><span>{done} / {total}</span></div>
    <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-bg-tertiary" role="progressbar" aria-label={label} aria-valuenow={done} aria-valuemin={0} aria-valuemax={total}>
      <div className="h-full rounded-full bg-green-500/70" style={{ width: `${percent}%` }} />
    </div>
  </div>
}

function ModeSelector({ mode, busy, onMode }: { mode: SeriesProductionMode; busy: boolean; onMode: (mode: SeriesProductionMode) => void }) {
  const { t } = useUiTranslation('seriesLab')
  return <div role="radiogroup" aria-label={t('approval.mode.label')} className="space-y-1">
    <div className="grid grid-cols-3 gap-1">
      {PRODUCTION_MODES.map(value => <button key={value} type="button" role="radio" aria-checked={mode === value} disabled={busy}
        className={`min-h-10 rounded-lg border px-2 py-1.5 text-[11px] sm:min-h-0 ${mode === value ? 'border-violet-400 bg-violet-500/20 text-violet-100' : 'border-border text-text-secondary hover:bg-bg-hover'}`}
        onClick={() => { if (value !== mode) onMode(value) }}>{t(`approval.mode.${value}.label`)}</button>)}
    </div>
    <p className="text-[10px] text-text-muted">{t(`approval.mode.${mode}.hint`)}</p>
  </div>
}

function RenderStatus({ render }: { render: ApprovalRender }) {
  const { t } = useUiTranslation('seriesLab')
  const job = render.job
  if (!job) return null
  const done = job.items.filter(item => item.status === 'done').length
  return <p role="status" className="flex flex-wrap items-center gap-2 text-[11px] text-text-secondary">
    {render.live && <Loader2 size={12} className="animate-spin" />}
    {t('approval.render.progress', { done, total: job.items.length, status: t(`serverRender.status.${job.status}`) })}
    {Boolean(job.waiting?.length) && <Pill tone="amber">{t('approval.render.waiting', { count: job.waiting!.length })}</Pill>}
    {render.live && <button type="button" className={secondaryButton} disabled={job.status === 'cancelling'} onClick={render.stop}><Square size={12} />{t('serverRender.stop')}</button>}
  </p>
}

function NextStep({ summary, render, onFilter, onApproveVisible, onOpenResults }: {
  summary: ReviewSummary; render: ApprovalRender; onFilter: (filter: ReviewFilter) => void
  onApproveVisible: () => void; onOpenResults?: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const { kind, count } = summary.nextStep
  const renderAction = summary.mode !== 'direct' ? RENDER_ACTIONS[kind] : undefined
  return <div className="flex flex-wrap items-center gap-2">
    <p className="mr-auto text-xs font-medium text-text-primary">{t(`approval.next.${kind}`, { count })}</p>
    {kind === 'approve_plan' && <button type="button" className={`${greenButton} ${big}`} onClick={onApproveVisible}><CheckCheck size={13} />{t('approval.actions.approveVisible')}</button>}
    {(kind === 'approve_plan' || kind === 'approve_previews') && <button type="button" className={`${secondaryButton} ${big}`} onClick={() => onFilter('pending')}>{t('approval.actions.showPending')}</button>}
    {kind === 'changes' && <button type="button" className={`${secondaryButton} ${big}`} onClick={() => onFilter('changes')}>{t('approval.actions.showChanges')}</button>}
    {renderAction && <button type="button" className={`${primaryButton} ${big}`} disabled={render.live || render.busy} onClick={() => void render.start()}>
      <Film size={13} />{t(renderAction)}</button>}
    {kind === 'assemble' && onOpenResults && <button type="button" className={`${primaryButton} ${big}`} onClick={onOpenResults}>{t('approval.actions.openResults')}</button>}
  </div>
}

export function SeriesApprovalHeader({ summary, render, busy, cast, onMode, onFilter, onApproveVisible, onOpenFaceRig, onOpenResults }: {
  summary: ReviewSummary; render: ApprovalRender; busy: boolean; cast: CastMember[]
  onMode: (mode: SeriesProductionMode) => void; onFilter: (filter: ReviewFilter) => void; onApproveVisible: () => void
  onOpenFaceRig?: (characterId: string, poseId?: string) => void; onOpenResults?: () => void
}) {
  const { t } = useUiTranslation('seriesLab')
  const { mode, total } = summary
  const others = summary.steps.filter(step => step.kind !== summary.nextStep.kind)
  return <section aria-label={t('approval.title')} className="space-y-3 rounded-xl border border-border bg-bg-secondary p-3">
    <div className="grid gap-3 lg:grid-cols-[minmax(0,22rem)_1fr]">
      <ModeSelector mode={mode} busy={busy} onMode={onMode} />
      <div className="flex flex-wrap gap-3">
        {mode !== 'direct' && <Progress label={t('approval.progress.plan')} done={summary.plan.approved} total={total} />}
        {mode !== 'plan' && <Progress label={t(mode === 'preview' ? 'approval.progress.preview' : 'approval.progress.reviewed')} done={mode === 'preview' ? summary.preview.approved : summary.filters.approved} total={total} />}
        <Progress label={t('approval.progress.ready')} done={summary.ready} total={total} />
      </div>
    </div>
    <NextStep summary={summary} render={render} onFilter={onFilter} onApproveVisible={onApproveVisible} onOpenResults={onOpenResults} />
    {others.length > 0 && <p className="flex flex-wrap gap-1">{others.map(step => <Pill key={step.kind} tone={step.kind === 'changes' ? 'amber' : 'neutral'}>{t(`approval.steps.${step.kind}`, { count: step.count })}</Pill>)}</p>}
    <div className="flex flex-wrap items-center gap-2">
      {mode !== 'direct' && <button type="button" className={`${secondaryButton} ${big}`} disabled={render.live || render.busy} onClick={() => void render.start()}>
        <RotateCcw size={13} />{t('approval.actions.rerenderChanged')}</button>}
      <RenderStatus render={render} />
      {render.error && <p role="alert" className="text-[11px] text-red-300">{render.error}</p>}
    </div>
    {onOpenFaceRig && cast.length > 0 && <details className="text-[11px]">
      <summary className="cursor-pointer text-text-secondary">{t('approval.cast.title', { count: cast.length })}</summary>
      <div className="mt-2 flex flex-wrap gap-1.5">{cast.map(member => <button key={member.characterId} type="button" className={`${secondaryButton} ${big}`}
        onClick={() => onOpenFaceRig(member.characterId, member.poseId)}><Smile size={13} />{t('approval.cast.faceRig', { name: member.name })}</button>)}</div>
    </details>}
  </section>
}
