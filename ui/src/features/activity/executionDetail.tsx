import { AlertCircle, CheckCircle2, CircleSlash2, Copy, Loader2 } from 'lucide-react'
import { canResumeCanonicalTask, canonicalTaskVisualState } from '../../lib/canonicalTaskEvents'
import { formatAppAction, formatAppTimestamp } from '../../lib/locale'
import { useUiTranslation } from '../../i18n'
import type { CanonicalTask } from '../../api/client'
import {
  isLiveStatus,
  taskProgressPercent,
  type ActivityAttempt,
  type ActivityGroup,
  type ActivityJob,
  type ActivityReadingState,
  type ActivityTaskLike,
} from './lineage'
import {
  estimatedRemainingSeconds,
  formatElapsed,
  formatEta,
  generationInitiator,
  generationPrompt,
  generationRecipe,
  resourceSummary,
  translatedPhase,
  truncatePrompt,
} from './taskPresentation'

export type TaskControlAction = 'cancel' | 'resume' | 'dismiss'
export interface TaskControlFailure {
  action: TaskControlAction
  message: string
}

interface ActivityExecutionDetailProps {
  group: ActivityGroup
  clock: number
  selected: boolean
  expanded: boolean
  inspectedAttemptId?: string
  busyIds: Set<string>
  controlFailures: Record<string, TaskControlFailure>
  onSelect: () => void
  onToggleExpand: () => void
  onInspectPrevious: () => void
  onControl: (task: CanonicalTask, action: TaskControlAction) => void
  onCopyId: (task: CanonicalTask) => void
  onCopyPrompt: (task: CanonicalTask) => void
  onOpenArtifact: (name: string) => void
  onOpenProject: () => void
}

type Translate = (key: string, options?: object) => string

function asTranslate(t: unknown): Translate {
  return t as Translate
}

function readingClass(state: ActivityReadingState): string {
  if (state === 'failed') return 'text-red-400'
  if (state === 'running') return 'text-accent-blue'
  if (state === 'partial') return 'text-amber-300'
  if (state === 'completed') return 'text-emerald-400'
  if (state === 'admitted') return 'text-violet-300'
  if (state === 'prepared') return 'text-violet-300'
  return 'text-text-muted'
}

function StatusIcon({ status }: { status: string }) {
  const visual = canonicalTaskVisualState(status)
  if (visual === 'active') return <Loader2 size={12} className="mt-0.5 shrink-0 animate-spin text-accent-blue" />
  if (visual === 'error') return <AlertCircle size={12} className="mt-0.5 shrink-0 text-red-400" />
  if (visual === 'cancelled') return <CircleSlash2 size={12} className="mt-0.5 shrink-0 text-text-muted" />
  return <CheckCircle2 size={12} className="mt-0.5 shrink-0 text-emerald-400" />
}

function phaseText(t: Translate, task: ActivityTaskLike): string {
  return translatedPhase(t, task)
}

function AttemptRow({ attempt, inspected }: { attempt: ActivityAttempt; inspected: boolean }) {
  const { t: tRaw } = useUiTranslation('activity')
  const t = asTranslate(tRaw)
  const extra = attempt.error || attempt.message
  return (
    <p
      data-attempt-id={attempt.id}
      data-inspected={inspected ? 'true' : undefined}
      className={`text-[8px] ${inspected ? 'text-amber-200' : 'text-text-muted'}`}
    >
      {t('lineage.previousAttempt', { n: attempt.attempt })}
      {extra ? ` · ${extra}` : ''}
      {attempt.resultRefs.length ? ` · ${attempt.resultRefs.join(', ')}` : ''}
    </p>
  )
}

function EtaSuffix({ task, clock, t }: { task: ActivityTaskLike; clock: number; t: Translate }) {
  if (!isLiveStatus(task.status)) return null
  const eta = formatEta(estimatedRemainingSeconds(task, clock))
  if (!eta) return null
  return <>{` · ${t('eta', { value: eta })}`}</>
}

function TokenSpan({ task, t }: { task: ActivityTaskLike; t: Translate }) {
  if (!task.token_usage?.total) return null
  return (
    <span>
      {t('tokens', {
        total: task.token_usage.total.toLocaleString(),
        prompt: task.token_usage.prompt || 0,
        completion: task.token_usage.completion || 0,
      })}
    </span>
  )
}

function JobHeadline({ job, clock, t }: { job: ActivityJob; clock: number; t: Translate }) {
  const child = job.task
  return (
    <p>
      <span className={readingClass(job.readingState)}>{t(`lineage.reading.${job.readingState}`)}</span>
      {' · '}
      {phaseText(t, child)}
      {' · '}
      {formatElapsed(child, clock)}
      {' · '}
      {child.message}
      <EtaSuffix task={child} clock={clock} t={t} />
    </p>
  )
}

function JobMeta({
  child,
  t,
  onCopyId,
}: {
  child: ActivityTaskLike
  t: Translate
  onCopyId: (task: CanonicalTask) => void
}) {
  const recipe = generationRecipe(child)
  const resources = resourceSummary(child)
  const initiator = generationInitiator(child)
  return (
    <p className="flex flex-wrap gap-x-2 text-[8px] text-text-muted">
      {recipe ? <span className="text-amber-300">{recipe}</span> : null}
      {initiator ? <span className="text-violet-300">{t('startedBy', { name: initiator })}</span> : null}
      {child.server_origin ? <span>{t('server', { origin: child.server_origin })}</span> : null}
      {resources ? <span className="text-accent-blue">{t(`resources.${resources.kind}`, { value: resources.value })}</span> : null}
      <span>{t('attempt', { current: child.attempt || 1, max: child.max_attempts || 1 })}</span>
      <TokenSpan task={child} t={t} />
      <button type="button" onClick={() => onCopyId(child as CanonicalTask)} className="font-mono hover:text-text-primary" title={t('copyChildTaskId')}>
        {child.id}
      </button>
    </p>
  )
}

function JobPrompt({
  child,
  t,
  onCopyPrompt,
}: {
  child: ActivityTaskLike
  t: Translate
  onCopyPrompt: (task: CanonicalTask) => void
}) {
  const prompt = generationPrompt(child)
  if (!prompt) return null
  return (
    <button
      type="button"
      onClick={() => onCopyPrompt(child as CanonicalTask)}
      className="block max-w-full truncate text-left text-[8px] text-text-secondary hover:text-text-primary"
      title={t('copyPromptTitle', { prompt })}
      aria-label={t('copyPrompt', { title: child.title || child.id })}
    >
      {t('prompt')}: {truncatePrompt(prompt, 140)} <Copy size={8} className="inline" />
    </button>
  )
}

function JobRow({
  job,
  clock,
  inspectedAttemptId,
  onCopyId,
  onCopyPrompt,
}: {
  job: ActivityJob
  clock: number
  inspectedAttemptId?: string
  onCopyId: (task: CanonicalTask) => void
  onCopyPrompt: (task: CanonicalTask) => void
}) {
  const { t: tRaw } = useUiTranslation('activity')
  const t = asTranslate(tRaw)
  const child = job.task
  const previous = job.attempts.filter(attempt => attempt.id !== `${child.id}:${child.attempt || 1}`)
  return (
    <div className="mb-1 last:mb-0" title={child.detail || child.message} data-job-id={job.id} data-reading-state={job.readingState}>
      <JobHeadline job={job} clock={clock} t={t} />
      <JobMeta child={child} t={t} onCopyId={onCopyId} />
      <JobPrompt child={child} t={t} onCopyPrompt={onCopyPrompt} />
      {previous.map(attempt => (
        <AttemptRow key={attempt.id} attempt={attempt} inspected={attempt.id === inspectedAttemptId} />
      ))}
    </div>
  )
}

function GroupTaskControls({
  task,
  active,
  busyIds,
  onControl,
  t,
  tCommon,
}: {
  task: CanonicalTask
  active: boolean
  busyIds: Set<string>
  onControl: (task: CanonicalTask, action: TaskControlAction) => void
  t: Translate
  tCommon: Translate
}) {
  if (active && task.cancelable) {
    return (
      <button type="button" disabled={busyIds.has(task.id)} onClick={() => onControl(task, 'cancel')} className="rounded border border-red-400/40 px-1.5 py-0.5 text-[9px] text-red-300">
        {busyIds.has(task.id) ? t('cancelling') : tCommon('actions.cancel')}
      </button>
    )
  }
  if (!active && canResumeCanonicalTask(task)) {
    return (
      <button type="button" disabled={busyIds.has(task.id)} onClick={() => onControl(task, 'resume')} className="rounded border border-border px-1.5 py-0.5 text-[9px] text-accent-blue">{tCommon('actions.resume')}</button>
    )
  }
  if (!active) {
    return (
      <button type="button" disabled={busyIds.has(task.id)} onClick={() => onControl(task, 'dismiss')} className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted">{t('dismiss')}</button>
    )
  }
  return null
}

function GroupTitleRow({
  group,
  task,
  clock,
  active,
  busyIds,
  onSelect,
  onControl,
  t,
  tCommon,
}: {
  group: ActivityGroup
  task: CanonicalTask
  clock: number
  active: boolean
  busyIds: Set<string>
  onSelect: () => void
  onControl: (task: CanonicalTask, action: TaskControlAction) => void
  t: Translate
  tCommon: Translate
}) {
  const updatedAt = formatAppTimestamp(task.updated_at)
  const taskEta = formatEta(estimatedRemainingSeconds(task, clock))
  return (
    <div className="flex flex-wrap items-center justify-between gap-2">
      <button type="button" onClick={onSelect} className="min-w-0 text-left font-medium text-text-primary">
        {task.title}
      </button>
      <div className="flex items-center gap-2">
        <span className={`capitalize ${readingClass(group.readingState)}`}>{t(`lineage.reading.${group.readingState}`)}</span>
        <span className="tabular-nums text-text-muted" title={updatedAt ? `${formatAppAction('updated')}: ${updatedAt}` : undefined}>{formatElapsed(task, clock)}</span>
        {active && taskEta ? <span className="tabular-nums text-accent-blue" title={t('etaTitle')}>{t('eta', { value: taskEta })}</span> : null}
        {updatedAt ? <span className="hidden md:inline text-text-muted">{updatedAt}</span> : null}
        <span className="capitalize text-text-muted">{phaseText(t, task)}</span>
        <GroupTaskControls task={task} active={active} busyIds={busyIds} onControl={onControl} t={t} tCommon={tCommon} />
      </div>
    </div>
  )
}

function GroupPrompt({ task, t, onCopyPrompt }: { task: CanonicalTask; t: Translate; onCopyPrompt: (task: CanonicalTask) => void }) {
  const prompt = generationPrompt(task)
  if (!prompt) return null
  return (
    <div className="mt-1 flex min-w-0 items-center gap-1 rounded border border-border/70 bg-bg-tertiary/40 px-1.5 py-1 text-[9px]">
      <span className="shrink-0 text-text-muted">{t('prompt')}</span>
      <button
        type="button"
        onClick={() => onCopyPrompt(task)}
        className="min-w-0 flex-1 truncate text-left text-text-secondary hover:text-text-primary"
        title={t('copyPromptTitle', { prompt })}
        aria-label={t('copyPrompt', { title: task.title })}
      >
        {truncatePrompt(prompt)}
      </button>
      <button type="button" onClick={() => onCopyPrompt(task)} className="shrink-0 text-text-muted hover:text-text-primary" title={t('copyPromptIcon', { title: task.title })} aria-label={t('copyPromptIcon', { title: task.title })}>
        <Copy size={10} />
      </button>
    </div>
  )
}

function GroupActiveChild({ child, clock, t }: { child?: ActivityTaskLike; clock: number; t: Translate }) {
  if (!child) return null
  const eta = formatEta(estimatedRemainingSeconds(child, clock))
  return (
    <p className="text-[9px] text-violet-300">
      {t('activeSubtask', { phase: phaseText(t, child) })}
      {eta ? ` · ${t('eta', { value: eta })}` : ''}
    </p>
  )
}

function GroupControlFailure({
  task,
  failure,
  busyIds,
  onControl,
  t,
  tCommon,
}: {
  task: CanonicalTask
  failure?: TaskControlFailure
  busyIds: Set<string>
  onControl: (task: CanonicalTask, action: TaskControlAction) => void
  t: Translate
  tCommon: Translate
}) {
  if (!failure) return null
  return (
    <div aria-live="polite" className="mt-1.5 flex items-center justify-between gap-2 rounded border border-red-400/40 bg-red-500/10 px-2 py-1 text-[9px] text-red-300">
      <span>{t('controlFailed', { action: failure.action[0].toUpperCase() + failure.action.slice(1), message: failure.message })}</span>
      <button
        type="button"
        disabled={busyIds.has(task.id)}
        onClick={() => onControl(task, failure.action)}
        className="shrink-0 rounded border border-red-300/50 px-1.5 py-0.5 font-medium disabled:opacity-50"
        aria-label={t('retryAction', { action: failure.action })}
      >
        {tCommon('actions.retry')}
      </button>
    </div>
  )
}

function GroupIdentity({ task, t, onCopyId }: { task: CanonicalTask; t: Translate; onCopyId: (task: CanonicalTask) => void }) {
  return (
    <p className="mt-0.5 flex flex-wrap gap-x-2 text-[9px] text-text-muted">
      {task.server_origin ? <span>{t('server', { origin: task.server_origin })}</span> : null}
      <span>{t('attempt', { current: task.attempt, max: task.max_attempts })}</span>
      <TokenSpan task={task} t={t} />
      <button type="button" onClick={() => onCopyId(task)} className="font-mono hover:text-text-primary" title={t('copyTaskId')}>{task.id}</button>
    </p>
  )
}

function GroupActions({
  group,
  inspected,
  expanded,
  onOpenArtifact,
  onOpenProject,
  onInspectPrevious,
  onToggleExpand,
  t,
}: {
  group: ActivityGroup
  inspected?: ActivityAttempt
  expanded: boolean
  onOpenArtifact: (name: string) => void
  onOpenProject: () => void
  onInspectPrevious: () => void
  onToggleExpand: () => void
  t: Translate
}) {
  const canToggle = group.jobs.length > 1 || Boolean(group.previousAttempt) || group.artifacts.length > 0
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {group.artifacts.map(name => (
        <button key={name} type="button" onClick={() => onOpenArtifact(name)} className="rounded border border-emerald-400/30 px-1.5 py-0.5 text-[9px] text-emerald-300">
          {t('lineage.openArtifact', { name })}
        </button>
      ))}
      {group.readingState === 'admitted' && !group.hasArtifact ? <span className="text-[9px] text-violet-300">{t('lineage.admittedWaiting')}</span> : null}
      {group.project ? (
        <button type="button" onClick={onOpenProject} className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-secondary">
          {t('lineage.openProject')}
        </button>
      ) : null}
      {group.previousAttempt ? (
        <button type="button" onClick={onInspectPrevious} className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-secondary" aria-pressed={Boolean(inspected)}>
          {t('lineage.inspectPrevious')}
        </button>
      ) : null}
      {canToggle ? (
        <button type="button" onClick={onToggleExpand} className="rounded border border-border px-1.5 py-0.5 text-[9px] text-text-muted">
          {expanded ? t('lineage.hideDetails') : t('lineage.showDetails')}
        </button>
      ) : null}
    </div>
  )
}

function GroupProgressBar({ task, active }: { task: CanonicalTask; active: boolean }) {
  if (!active) return null
  const percent = taskProgressPercent(task)
  const label = task.total > 0 ? `${task.current}/${task.total}` : `${Math.round(percent)}%`
  return (
    <div className="mt-1.5 flex items-center gap-2">
      <div className="h-1 flex-1 overflow-hidden rounded-full bg-bg-tertiary">
        <div className="h-full rounded-full bg-accent-blue transition-[width] duration-300" style={{ width: `${Math.max(percent, percent > 0 ? 2 : 0)}%` }} />
      </div>
      <span className="w-12 text-right tabular-nums text-text-muted">{label}</span>
    </div>
  )
}

function inspectedAttempt(group: ActivityGroup, inspectedAttemptId?: string): ActivityAttempt | undefined {
  if (group.previousAttempt && group.previousAttempt.id === inspectedAttemptId) return group.previousAttempt
  return group.jobs.flatMap(job => job.attempts).find(attempt => attempt.id === inspectedAttemptId)
}

function GroupCopy({
  recipe,
  initiator,
  resources,
  t,
}: {
  recipe: string
  initiator: string
  resources: ReturnType<typeof resourceSummary>
  t: Translate
}) {
  return (
    <>
      {recipe ? <p className="mt-0.5 break-words text-[9px] text-amber-300">{recipe}</p> : null}
      {initiator ? <p className="mt-0.5 text-[9px] text-violet-300">{t('startedBy', { name: initiator })}</p> : null}
      {resources ? <p className="text-[9px] text-accent-blue">{t(`resources.${resources.kind}`, { value: resources.value })}</p> : null}
    </>
  )
}

function GroupChildren({
  jobs,
  clock,
  inspectedAttemptId,
  onCopyId,
  onCopyPrompt,
}: {
  jobs: ActivityJob[]
  clock: number
  inspectedAttemptId?: string
  onCopyId: (task: CanonicalTask) => void
  onCopyPrompt: (task: CanonicalTask) => void
}) {
  if (!jobs.length) return null
  return (
    <div className="mt-1 border-l border-border pl-2 text-[9px] text-text-muted">
      {jobs.map(job => (
        <JobRow
          key={job.id}
          job={job}
          clock={clock}
          inspectedAttemptId={inspectedAttemptId}
          onCopyId={onCopyId}
          onCopyPrompt={onCopyPrompt}
        />
      ))}
    </div>
  )
}

function GroupPrevious({ expanded, inspected }: { expanded: boolean; inspected?: ActivityAttempt }) {
  if (!expanded) return null
  if (!inspected) return null
  return (
    <div data-testid="activity-previous-attempt" className="mt-1 rounded border border-amber-400/30 bg-amber-400/5 px-1.5 py-1 text-[9px] text-amber-100">
      <AttemptRow attempt={inspected} inspected />
    </div>
  )
}

function GroupBody(props: ActivityExecutionDetailProps & { task: CanonicalTask; t: Translate; tCommon: Translate }) {
  const { task, t, tCommon } = props
  const children = props.group.jobs.filter(job => job.id !== task.id)
  const activeChild = props.group.jobs.map(job => job.task).find(child => isLiveStatus(child.status) && child.id !== task.id)
  const active = isLiveStatus(task.status)
  const inspected = inspectedAttempt(props.group, props.inspectedAttemptId)
  const failed = task.status === 'failed' || task.status === 'interrupted'
  return (
    <div className="min-w-0 flex-1">
      <GroupTitleRow
        group={props.group}
        task={task}
        clock={props.clock}
        active={active}
        busyIds={props.busyIds}
        onSelect={props.onSelect}
        onControl={props.onControl}
        t={t}
        tCommon={tCommon}
      />
      <p className="text-[9px] text-text-muted">
        {t('lineage.progressLabel')} {Math.round(props.group.progress)}%
        {' · '}
        {t('lineage.resultLabel')} {t(`lineage.reading.${props.group.readingState}`)}
        {props.group.jobs.length > 1 ? ` · ${t('lineage.jobs', { count: props.group.jobs.length })}` : ''}
      </p>
      <p className={failed ? 'text-red-400' : 'text-text-secondary'} title={task.detail || task.message}>
        {task.error?.message || task.detail || task.message}
      </p>
      <GroupCopy recipe={generationRecipe(task)} initiator={generationInitiator(task)} resources={resourceSummary(task)} t={t} />
      <GroupPrompt task={task} t={t} onCopyPrompt={props.onCopyPrompt} />
      {active ? <GroupActiveChild child={activeChild} clock={props.clock} t={t} /> : null}
      {props.group.recoveryReason ? <p role="status" className="mt-1 text-[9px] text-red-300">{t('lineage.recoveryReason', { reason: props.group.recoveryReason })}</p> : null}
      <GroupControlFailure task={task} failure={props.controlFailures[task.id]} busyIds={props.busyIds} onControl={props.onControl} t={t} tCommon={tCommon} />
      <GroupIdentity task={task} t={t} onCopyId={props.onCopyId} />
      <GroupActions
        group={props.group}
        inspected={inspected}
        expanded={props.expanded}
        onOpenArtifact={props.onOpenArtifact}
        onOpenProject={props.onOpenProject}
        onInspectPrevious={props.onInspectPrevious}
        onToggleExpand={props.onToggleExpand}
        t={t}
      />
      <GroupChildren
        jobs={children}
        clock={props.clock}
        inspectedAttemptId={props.inspectedAttemptId}
        onCopyId={props.onCopyId}
        onCopyPrompt={props.onCopyPrompt}
      />
      <GroupPrevious expanded={props.expanded} inspected={inspected} />
      <GroupProgressBar task={task} active={active} />
    </div>
  )
}

export function ActivityExecutionDetail(props: ActivityExecutionDetailProps) {
  const { t: tRaw } = useUiTranslation('activity')
  const { t: tCommonRaw } = useUiTranslation('common')
  const t = asTranslate(tRaw)
  const tCommon = asTranslate(tCommonRaw)
  const task = props.group.primary as CanonicalTask
  const border = props.selected ? 'border-accent-blue/70' : 'border-border'
  return (
    <div
      data-task-id={task.id}
      data-group-id={props.group.id}
      data-reading-state={props.group.readingState}
      data-receipt-id={props.group.receiptId || undefined}
      data-intent-id={props.group.intentId || undefined}
      role="group"
      aria-current={props.selected ? 'true' : undefined}
      aria-expanded={props.expanded}
      aria-label={t('lineage.groupAria', { title: props.group.title, state: t(`lineage.reading.${props.group.readingState}`) })}
      tabIndex={-1}
      className={`rounded-md border bg-bg-primary p-2 ${border}`}
    >
      <div className="flex items-start gap-2">
        <StatusIcon status={task.status} />
        <GroupBody {...props} task={task} t={t} tCommon={tCommon} />
      </div>
    </div>
  )
}
