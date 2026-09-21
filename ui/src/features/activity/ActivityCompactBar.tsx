import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp, CircleSlash2, ListVideo, Loader2 } from 'lucide-react'
import type { RefObject } from 'react'
import type { CanonicalTask } from '../../api/client'
import { canonicalTaskVisualState } from '../../lib/canonicalTaskEvents'
import { useStore } from '../../stores/useStore'
import { useUiTranslation } from '../../i18n'
import type { ActivityGroup, ActivityTaskLike } from './lineage'
import { isLiveStatus, taskProgressPercent } from './lineage'
import type { TaskControlAction } from './executionDetail'
import {
  estimatedRemainingSeconds,
  formatElapsed,
  formatEta,
  generationInitiator,
  generationPrompt,
  generationRecipe,
  truncatePrompt,
} from './taskPresentation'
import { translatedPhase as phaseText } from './taskPresentation'

interface ActivityCompactBarProps {
  detailsOpen: boolean
  liveCount: number
  clock: number
  primary?: CanonicalTask
  primaryGroup: ActivityGroup | null
  busyIds: Set<string>
  toggleRef: RefObject<HTMLButtonElement | null>
  onToggle: () => void
  onCopyPrompt: (task: CanonicalTask) => void
  onControl: (task: CanonicalTask, action: TaskControlAction) => void
}

function ToggleIcon({ isActive, hasError, visual }: { isActive: boolean; hasError: boolean; visual: string }) {
  if (isActive) return <Loader2 size={13} className="animate-spin text-accent-blue" />
  if (hasError) return <AlertCircle size={13} className="text-red-400" />
  if (visual === 'cancelled') return <CircleSlash2 size={13} className="text-text-muted" />
  return <CheckCircle2 size={13} className="text-emerald-400" />
}

type Translate = (key: string, options?: object) => string

function asTranslate(t: unknown): Translate {
  return t as Translate
}

function CompactSubtask({ child, clock, t }: { child?: ActivityTaskLike; clock: number; t: Translate }) {
  if (!child) return null
  const eta = formatEta(estimatedRemainingSeconds(child, clock))
  return (
    <span className="hidden lg:inline shrink-0 max-w-56 truncate text-violet-300" title={t('activeSubtask', { phase: child.message })}>
      {t('subtask', { phase: phaseText(t, child) })}
      {eta ? ` · ${t('eta', { value: eta })}` : ''}
    </span>
  )
}

function CompactToggle({
  detailsOpen,
  liveCount,
  isActive,
  hasError,
  visual,
  toggleRef,
  onToggle,
  t,
}: {
  detailsOpen: boolean
  liveCount: number
  isActive: boolean
  hasError: boolean
  visual: string
  toggleRef: RefObject<HTMLButtonElement | null>
  onToggle: () => void
  t: Translate
}) {
  return (
    <button
      ref={toggleRef}
      type="button"
      onClick={onToggle}
      className="flex items-center gap-1.5 shrink-0"
      aria-expanded={detailsOpen}
      aria-controls={detailsOpen ? 'activity-details' : undefined}
      title={t('openHistory')}
    >
      <ToggleIcon isActive={isActive} hasError={hasError} visual={visual} />
      <span className="font-medium text-text-primary">{t('title')}</span>
      {liveCount > 0 ? <span className="rounded-full bg-accent-blue/15 px-1.5 py-0.5 text-accent-blue tabular-nums">{liveCount}</span> : null}
      {detailsOpen ? <ChevronDown size={11} /> : <ChevronUp size={11} />}
    </button>
  )
}

function CompactSummary({
  primary,
  clock,
  t,
  onCopyPrompt,
}: {
  primary?: CanonicalTask
  clock: number
  t: Translate
  onCopyPrompt: (task: CanonicalTask) => void
}) {
  if (!primary) return null
  const eta = formatEta(estimatedRemainingSeconds(primary, clock))
  const prompt = generationPrompt(primary)
  const initiator = generationInitiator(primary)
  return (
    <>
      <span className="hidden sm:inline shrink-0 capitalize text-text-muted">{phaseText(t, primary)}</span>
      <span className="shrink-0 tabular-nums text-text-muted">{formatElapsed(primary, clock)}</span>
      {eta ? <span className="hidden sm:inline shrink-0 tabular-nums text-accent-blue" title={t('etaTitle')}>{t('eta', { value: eta })}</span> : null}
      {primary.model ? <span className="hidden md:inline max-w-64 shrink-0 truncate rounded border border-amber-400/30 bg-amber-400/10 px-1.5 py-0.5 text-amber-300" title={generationRecipe(primary)}>{primary.model}</span> : null}
      {initiator ? <span className="hidden lg:inline max-w-48 shrink-0 truncate text-violet-300" title={initiator}>{initiator}</span> : null}
      {prompt ? (
        <button type="button" onClick={() => onCopyPrompt(primary)} className="hidden xl:block min-w-0 max-w-80 truncate text-left text-text-secondary hover:text-text-primary" title={t('copyPromptTitle', { prompt })} aria-label={t('copyBarPrompt', { title: primary.title })}>
          “{truncatePrompt(prompt, 100)}”
        </button>
      ) : null}
    </>
  )
}

function CompactProgress({ primary }: { primary?: CanonicalTask }) {
  if (!primary) return null
  const percent = taskProgressPercent(primary)
  const label = primary.total > 0 ? `${primary.current}/${primary.total}` : `${Math.round(percent)}%`
  return (
    <div className="hidden sm:flex items-center gap-2 w-52 shrink-0">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
        <div className="h-full rounded-full bg-accent-blue transition-[width] duration-500" style={{ width: `${Math.max(percent, percent > 0 ? 2 : 0)}%` }} />
      </div>
      <span className="w-10 text-right tabular-nums text-text-secondary">{label}</span>
    </div>
  )
}

function CompactCancel({
  primary,
  busyIds,
  onControl,
  t,
  tCommon,
}: {
  primary?: CanonicalTask
  busyIds: Set<string>
  onControl: (task: CanonicalTask, action: TaskControlAction) => void
  t: Translate
  tCommon: Translate
}) {
  if (!primary) return null
  if (!isLiveStatus(primary.status)) return null
  if (!primary.cancelable) return null
  const busy = busyIds.has(primary.id)
  return (
    <button type="button" disabled={busy} onClick={() => onControl(primary, 'cancel')} className="flex shrink-0 items-center gap-1 rounded-md border border-red-400/40 px-2 py-1 text-red-300 disabled:opacity-50">
      {busy ? <Loader2 size={11} className="animate-spin" /> : null}
      <span>{busy ? t('cancelling') : tCommon('actions.cancel')}</span>
    </button>
  )
}

function compactHasError(isActive: boolean, primary?: CanonicalTask, primaryGroup: ActivityGroup | null = null): boolean {
  if (isActive) return false
  if (primary?.status === 'failed') return true
  if (primary?.status === 'interrupted') return true
  return primaryGroup?.readingState === 'failed'
}

function compactMessage(primary: CanonicalTask | undefined, fallback: string): string {
  if (primary?.error?.message) return primary.error.message
  if (primary?.detail) return primary.detail
  if (primary?.message) return primary.message
  return fallback
}

function compactVisual(primary?: CanonicalTask): string {
  if (!primary) return 'neutral'
  return canonicalTaskVisualState(primary.status)
}

function liveChild(group: ActivityGroup | null, primary?: CanonicalTask): ActivityTaskLike | undefined {
  if (!group) return undefined
  return group.jobs.map(job => job.task).find(child => isLiveStatus(child.status) && child.id !== primary?.id)
}

function CompactWorkspaces({ t }: { t: Translate }) {
  const setVideoWorkflowsOpen = useStore(state => state.setDashboardOpen)
  return (
    <button onClick={() => {
      useStore.getState().setMediaFilter('runs')
      setVideoWorkflowsOpen(false)
    }} className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-text-secondary hover:border-accent-blue/50 hover:text-accent-blue transition-colors shrink-0" title={t('workspacesTitle')}>
      <ListVideo size={12} /><span className="hidden sm:inline">{t('workspaces')}</span>
    </button>
  )
}

export function ActivityCompactBar({
  detailsOpen,
  liveCount,
  clock,
  primary,
  primaryGroup,
  busyIds,
  toggleRef,
  onToggle,
  onCopyPrompt,
  onControl,
}: ActivityCompactBarProps) {
  const { t: tCommonRaw } = useUiTranslation('common')
  const { t: tActivityRaw } = useUiTranslation('activity')
  const tCommon = asTranslate(tCommonRaw)
  const tActivity = asTranslate(tActivityRaw)
  const isActive = liveCount > 0
  const hasError = compactHasError(isActive, primary, primaryGroup)
  const message = compactMessage(primary, tActivity('ready'))
  const messageClass = hasError ? 'text-red-400' : isActive ? 'text-text-secondary' : 'text-text-muted'
  return (
    <>
      <CompactToggle
        detailsOpen={detailsOpen}
        liveCount={liveCount}
        isActive={isActive}
        hasError={hasError}
        visual={compactVisual(primary)}
        toggleRef={toggleRef}
        onToggle={onToggle}
        t={tActivity}
      />
      <div className="min-w-0 flex-1 flex items-center gap-2">
        <CompactSummary primary={primary} clock={clock} t={tActivity} onCopyPrompt={onCopyPrompt} />
        <CompactSubtask child={liveChild(primaryGroup, primary)} clock={clock} t={tActivity} />
        <span className={`truncate ${messageClass}`} title={message}>{message}</span>
      </div>
      {isActive ? <CompactProgress primary={primary} /> : null}
      <CompactCancel primary={primary} busyIds={busyIds} onControl={onControl} t={tActivity} tCommon={tCommon} />
      <CompactWorkspaces t={tActivity} />
    </>
  )
}
