import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Download, RefreshCw, X } from 'lucide-react'
import { isSameProduction } from './activityOpen.ts'
import { interpolate, reviewCopy, type ReviewCopy } from './copy.ts'
import { approveShot, persistCommandsFor, rejectShot, setShotNotes } from './decisions.ts'
import { exportApprovedSelection } from './exportSelection.ts'
import { applyRegenPlan, planSubsetRegeneration } from './regenerate.ts'
import { canApproveTake, isTakeCompleted } from './status.ts'
import { comparePair, restoreCompareChoices, selectExactTake, setCompareTake } from './takes.ts'
import type {
  ActivityOpenSource, ExportSelection, PersistCommand, RegenOutcome, RegenPlan, ReviewDesk, ReviewShot, ReviewTake,
} from './types.ts'

const chip = 'rounded border border-border px-2 py-1 text-[10px]'
const action = `${chip} inline-flex items-center gap-1 hover:bg-bg-hover disabled:opacity-40`

export interface ProductionReviewDeskProps {
  desk: ReviewDesk
  onChange?: (desk: ReviewDesk) => void
  onPersist?: (commands: PersistCommand[]) => void | ReviewDesk | Promise<void | ReviewDesk>
  onRegenerate?: (plan: RegenPlan) => Promise<RegenOutcome[]>
  onExport?: (selection: ExportSelection) => Promise<void>
  activityTarget?: ActivityOpenSource | null
  fileUrl?: (filename: string) => string
}

function durationLabel(copy: ReviewCopy, seconds: number | null | undefined): string {
  if (seconds == null) return copy.noDuration
  return interpolate(copy.duration, { seconds: Number(seconds).toFixed(1) })
}

function TakeStage({
  label, take, copy, fileUrl, selected, onSelect,
}: {
  label: string
  take: ReviewTake | null
  copy: ReviewCopy
  fileUrl: (filename: string) => string
  selected: boolean
  onSelect: () => void
}) {
  const source = take?.filename ? fileUrl(take.filename) : ''
  const [measured, setMeasured] = useState<{ source: string; seconds: number } | null>(null)
  const duration = measured?.source === source ? measured.seconds : take?.durationSeconds
  return (
    <article data-testid={label === copy.takeA ? 'take-a' : 'take-b'} className={`rounded-lg border p-2 ${selected ? 'border-emerald-400 bg-emerald-500/10' : 'border-border'}`}>
      <div className="mb-1 flex items-center justify-between gap-2 text-[10px]">
        <span>{label}</span>
        <span>{take ? interpolate(copy.status, { value: copy[take.status] || take.status }) : copy.noTake}</span>
      </div>
      {take?.filename
        ? <video key={source} className="aspect-video w-full rounded bg-black" src={source} controls preload="metadata" data-take-id={take.id}
            onLoadedMetadata={event => {
              const seconds = event.currentTarget.duration
              if (Number.isFinite(seconds) && seconds > 0) setMeasured({ source, seconds })
            }} />
        : <div className="flex aspect-video items-center justify-center rounded bg-black/70 text-[10px] text-text-muted">{take ? copy[take.status] : copy.noTake}</div>}
      <p className="mt-1 truncate font-mono text-[9px]" title={take?.id}>{take ? interpolate(copy.take, { id: take.id }) : copy.noTake}</p>
      <p className="text-[9px] text-text-muted">{durationLabel(copy, duration)}</p>
      {take && <button type="button" className={`${action} mt-1`} onClick={onSelect} aria-pressed={selected}>{copy.selectTake}</button>}
    </article>
  )
}

function ShotRail({
  desk, copy, focusId, picked, onFocus, onToggle,
}: {
  desk: ReviewDesk
  copy: ReviewCopy
  focusId: string
  picked: string[]
  onFocus: (id: string) => void
  onToggle: (id: string, checked: boolean) => void
}) {
  return (
    <nav className="max-h-[40rem] overflow-y-auto border-b border-border p-2 lg:border-b-0 lg:border-r" aria-label={copy.title}>
      {desk.shots.map((shot, index) => (
        <div key={shot.id} className={`mb-1.5 rounded border p-2 ${shot.id === focusId ? 'border-violet-400 bg-violet-500/15' : 'border-border'}`}>
          <label className="flex items-center gap-2 text-[10px]">
            <input
              type="checkbox"
              checked={picked.includes(shot.id)}
              disabled={shot.decision === 'approved'}
              onChange={event => onToggle(shot.id, event.target.checked)}
              aria-label={interpolate(copy.shot, { n: index + 1 })}
            />
            <button type="button" className="min-w-0 flex-1 text-left" onClick={() => onFocus(shot.id)}>
              <span>{interpolate(copy.shot, { n: index + 1 })}</span>
              <span className="ml-2 text-text-muted">{copy[shot.decision]}</span>
              {shot.selectedTakeId && <span className="mt-1 block truncate font-mono text-[8px]" data-selected-take={shot.selectedTakeId}>{shot.selectedTakeId}</span>}
            </button>
          </label>
        </div>
      ))}
    </nav>
  )
}

function DecisionBar({
  shot, copy, busy, onApprove, onReject, onNotes,
}: {
  shot: ReviewShot
  copy: ReviewCopy
  busy: boolean
  onApprove: () => void
  onReject: () => void
  onNotes: (value: string) => void
}) {
  const take = shot.takes.find(item => item.id === shot.selectedTakeId)
  return (
    <div className="mt-2 space-y-2">
      <p className="text-[10px] text-text-muted">{durationLabel(copy, take?.durationSeconds ?? shot.durationSeconds)}</p>
      <p className="text-[10px] text-text-muted">{shot.refs.length ? interpolate(copy.refs, { list: shot.refs.join(', ') }) : copy.noRefs}</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={action} disabled={!canApproveTake(take)} onClick={onApprove}><Check size={12} />{copy.approve}</button>
        <button type="button" className={action} onClick={onReject}><X size={12} />{copy.reject}</button>
      </div>
      <label className="block text-[10px]">{copy.notes}
        <textarea
          className="mt-1 min-h-16 w-full rounded border border-border bg-bg-secondary p-2 text-[11px]"
          key={`${shot.id}:${shot.notes}`}
          defaultValue={shot.notes}
          placeholder={copy.notesPlaceholder}
          aria-label={copy.notes}
          disabled={busy}
          onBlur={event => { if (event.target.value !== shot.notes) onNotes(event.target.value) }}
        />
      </label>
    </div>
  )
}

function ConfirmRegen({
  copy, count, onCancel, onConfirm,
}: {
  copy: ReviewCopy
  count: number
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <div role="dialog" aria-label={copy.regenerateConfirmTitle} className="mt-3 rounded-lg border border-amber-400/50 bg-amber-500/10 p-3 text-[11px]">
      <p className="font-medium">{copy.regenerateConfirmTitle}</p>
      <p className="mt-1">{interpolate(copy.regenerateConfirm, { count })}</p>
      <p className="mt-1 text-text-muted">{copy.keepApproved}</p>
      <div className="mt-2 flex gap-2">
        <button type="button" className={action} onClick={onConfirm}>{copy.confirm}</button>
        <button type="button" className={action} onClick={onCancel}>{copy.cancel}</button>
      </div>
    </div>
  )
}

export function ProductionReviewDesk({
  desk, onChange, onPersist, onRegenerate, onExport, activityTarget, fileUrl,
}: ProductionReviewDeskProps) {
  const copy = reviewCopy()
  const [current, setCurrent] = useState(desk)
  const [focusId, setFocusId] = useState(desk.shots[0]?.id || '')
  const [picked, setPicked] = useState<string[]>([])
  const [confirm, setConfirm] = useState(false)
  const [exportNote, setExportNote] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const pending = useRef(false)
  const queued = useRef<Array<() => Promise<void>>>([])
  const desired = useRef(desk)
  const committed = useRef(desk)
  useEffect(() => {
    if (pending.current) return
    const refreshed = restoreCompareChoices(committed.current, desk)
    desired.current = refreshed
    committed.current = refreshed
    setCurrent(refreshed)
  }, [desk])
  const shot = current.shots.find(item => item.id === focusId) || current.shots[0]
  const pair = useMemo(() => shot ? comparePair(shot) : { a: null, b: null }, [shot])
  const media = fileUrl || ((filename: string) => `#${filename}`)
  const fromActivity = isSameProduction(current, activityTarget)
  const run = async (operation: () => Promise<void>) => {
    if (pending.current) {
      queued.current.push(operation)
      return
    }
    pending.current = true; setBusy(true)
    let currentOp: (() => Promise<void>) | undefined = operation
    try {
      while (currentOp) {
        try { await currentOp(); setError('') } catch (reason) {
          setError(reason instanceof Error ? reason.message : String(reason))
        }
        currentOp = queued.current.shift()
      }
    } finally {
      desired.current = committed.current
      pending.current = false; setBusy(false)
    }
  }
  const save = async (next: ReviewDesk, shotIds?: string[]) => {
    if (!onPersist) throw new Error(copy.unavailable)
    const saved = restoreCompareChoices(next, await onPersist(persistCommandsFor(next, shotIds)) || next)
    committed.current = saved
    desired.current = saved
    setCurrent(saved); onChange?.(saved)
  }
  const persist = (mutate: (desk: ReviewDesk) => ReviewDesk, shotIds?: string[]) => {
    void run(async () => {
      const next = mutate(desired.current)
      desired.current = next
      await save(next, shotIds)
    })
  }

  const togglePick = (id: string, checked: boolean) => {
    setPicked(current => checked ? [...new Set([...current, id])] : current.filter(item => item !== id))
  }

  const runExport = () => void run(async () => {
    const selection = exportApprovedSelection(committed.current)
    if (!selection.clips.length) { setExportNote(copy.exportEmpty); return }
    if (!onExport) throw new Error(copy.unavailable)
    await onExport(selection)
    setExportNote(copy.exportStarted)
  })

  const runRegen = () => run(async () => {
    const plan = planSubsetRegeneration(desired.current, picked, { confirm: true, copy })
    if (!onRegenerate) throw new Error(copy.unavailable)
    const outcomes = await onRegenerate(plan)
    const next = applyRegenPlan(desired.current, plan, outcomes, { copy })
    desired.current = next
    await save(next, plan.jobs.map(job => job.shotId))
    setConfirm(false)
    setPicked([])
  })

  if (!shot) {
    return <section role="region" className="rounded-xl border border-border p-4 text-sm" aria-label={copy.title}><h2>{copy.title}</h2><p>{copy.empty}</p></section>
  }

  return (
    <section role="region" className="rounded-xl border border-border bg-bg-secondary p-3 text-text-primary" aria-label={copy.title} data-production-id={current.productionId}>
      {error && <p role="alert" className="mb-2 text-sm text-red-300">{error}</p>}
      <div className="mb-2 min-h-5">{busy && <p role="status" className="text-sm">{copy.working}</p>}</div>
      <fieldset disabled={!onPersist}>
      <header className="mb-2 flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold">{copy.title}</h2>
        {fromActivity && <span className="text-[10px] text-violet-300">{copy.openedFromActivity}</span>}
        <button type="button" className={action} onClick={() => setConfirm(true)} disabled={busy || !picked.length || !onRegenerate}><RefreshCw size={12} />{copy.regenerate}</button>
        <button type="button" className={action} onClick={runExport} disabled={busy || !onExport}><Download size={12} />{copy.export}</button>
      </header>
      {exportNote && <p role="status" className="mb-2 text-[10px]">{exportNote}</p>}
      {confirm && <fieldset disabled={busy}><ConfirmRegen copy={copy} count={picked.length} onCancel={() => setConfirm(false)} onConfirm={() => void runRegen()} /></fieldset>}
      <div className="grid min-h-72 overflow-hidden rounded-lg border border-border lg:grid-cols-[16rem_minmax(0,1fr)]">
        <fieldset disabled={busy}><ShotRail desk={current} copy={copy} focusId={shot.id} picked={picked} onFocus={setFocusId} onToggle={togglePick} /></fieldset>
        <div className="p-2">
          <p className="mb-2 text-[11px]">{copy.compare}</p>
          <div className="grid gap-2 sm:grid-cols-2">
            <TakeStage label={copy.takeA} take={pair.a} copy={copy} fileUrl={media} selected={pair.a?.id === shot.selectedTakeId} onSelect={() => { const take = pair.a; if (take) persist(desk => selectExactTake(desk, shot.id, take.id), [shot.id]) }} />
            <TakeStage label={copy.takeB} take={pair.b} copy={copy} fileUrl={media} selected={pair.b?.id === shot.selectedTakeId} onSelect={() => { const take = pair.b; if (take) persist(desk => selectExactTake(desk, shot.id, take.id), [shot.id]) }} />
          </div>
          <div className="mt-2 flex flex-wrap gap-1" aria-label={copy.selectTake}>
            {shot.takes.map(take => (
              <button
                key={take.id}
                type="button"
                data-take-id={take.id}
                className={`${chip} ${take.id === shot.selectedTakeId ? 'bg-emerald-500/20' : ''}`}
                aria-pressed={take.id === shot.selectedTakeId}
                onClick={() => persist(desk => selectExactTake(desk, shot.id, take.id), [shot.id])}
                onContextMenu={event => { event.preventDefault(); persist(desk => setCompareTake(desk, shot.id, take.id), [shot.id]) }}
              >
                {take.id}{isTakeCompleted(take) ? '' : ` · ${copy[take.status]}`}
              </button>
            ))}
          </div>
          <DecisionBar
            shot={shot}
            copy={copy}
            busy={busy}
            onApprove={() => persist(desk => approveShot(desk, shot.id), [shot.id])}
            onReject={() => persist(desk => rejectShot(desk, shot.id), [shot.id])}
            onNotes={value => persist(desk => setShotNotes(desk, shot.id, value), [shot.id])}
          />
        </div>
      </div>
      </fieldset>
    </section>
  )
}
