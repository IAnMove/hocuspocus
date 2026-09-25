import { useState } from 'react'
import { ModalShell } from '../../components/common/ModalShell'
import { planClone, planRetry, preflightGenerate } from './clone'
import { interpolate, inspectorCopy, type InspectorCopy } from './copy'
import { displayField } from './fields'
import { compareAttempts, copyRecipe } from './recipe'
import type {
  AttemptDiff, CanonicalRef, CatalogItem, CloneEnvironment, ClonePlan, CurrentModel,
  InspectedAttempt, PortableRecipe, PreflightReport, PromptChange, StoredField,
} from './types'

function promptBox(label: string, field: StoredField<string>, unknownLabel: string) {
  return (
    <section>
      <h3 className="text-[10px] uppercase tracking-wider text-text-muted">{label}</h3>
      <p data-field={label} className="whitespace-pre-wrap rounded border border-border bg-bg-tertiary/40 px-2 py-1.5 text-[11px] text-text-primary">
        {displayField(field, unknownLabel)}
      </p>
    </section>
  )
}

function ChangeList({ changes, copy }: { changes: PromptChange[]; copy: InspectorCopy }) {
  if (!changes.length) return <p className="text-[11px] text-text-muted">{copy.noTransform}</p>
  return (
    <ul data-testid="inspector-changes">
      {changes.map((change, index) => (
        <li key={`${change.source}-${change.field}-${index}`} className="text-[11px] text-text-secondary">
          {copy.changeSource[change.source]} · {change.field}: {displayField(change.before, copy.unknown)} → {displayField(change.after, copy.unknown)}
        </li>
      ))}
    </ul>
  )
}

function RefList({ refs, copy }: { refs: CanonicalRef[]; copy: InspectorCopy }) {
  if (!refs.length) return null
  return (
    <ul data-testid="inspector-refs">
      {refs.map((ref, index) => (
        <li key={`${ref.role}-${ref.assetId || ref.filename || index}`} className={ref.missing ? 'text-[11px] text-amber-300' : 'text-[11px] text-text-secondary'}>
          {ref.role}: {ref.assetId || ref.filename || copy.unknown}
          {ref.missing ? ` · ${copy.missingRef}` : ''}
        </li>
      ))}
    </ul>
  )
}

function DiffList({ diff, copy }: { diff: AttemptDiff; copy: InspectorCopy }) {
  return (
    <ul data-testid="inspector-diff">
      {diff.fields.filter(field => field.changed).map(field => (
        <li key={field.path} className="text-[11px] text-text-secondary">
          {field.path}: {field.left.known ? String(field.left.value ?? '') : copy.unknown}
          {' → '}
          {field.right.known ? String(field.right.value ?? '') : copy.unknown}
        </li>
      ))}
    </ul>
  )
}

function warningText(copy: InspectorCopy, code: string, role?: string, field?: string): string {
  if (code === 'model_mismatch') return copy.warnings.modelMismatch
  if (code === 'version_mismatch') return copy.warnings.versionMismatch
  if (code === 'missing_ref') return interpolate(copy.warnings.missingRef, { role: role || '' })
  if (code === 'unknown_field') return interpolate(copy.warnings.unknownField, { field: field || '' })
  if (code === 'empty_prompt') return copy.warnings.emptyPrompt
  if (code === 'workspace_mismatch') return copy.warnings.workspaceMismatch
  return code
}

async function writeClipboard(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value)
    return
  }
  throw new Error('clipboard')
}

function environment(
  workspace: string,
  catalog: CatalogItem[] | undefined,
  currentModel: CurrentModel | undefined,
): CloneEnvironment {
  return { workspace, catalog, currentModel }
}

function pickCompare(
  compareAttempt: InspectedAttempt | null | undefined,
  candidates: InspectedAttempt[],
  compareId: string,
  workspace: string,
): InspectedAttempt | null {
  const selected = compareAttempt || candidates.find(item => item.attemptId === compareId) || null
  if (!selected || selected.outputFolder !== workspace) return null
  return selected
}

function CompareSelect({
  copy, compareId, candidates, attemptId, workspace, onChange,
}: {
  copy: InspectorCopy
  compareId: string
  candidates: InspectedAttempt[]
  attemptId: string
  workspace: string
  onChange: (id: string) => void
}) {
  return (
    <label className="text-[10px] uppercase tracking-wider text-text-muted">
      {copy.compareWith}
      <select
        className="ml-2 rounded border border-border bg-bg-tertiary px-1 py-0.5 text-[11px]"
        value={compareId}
        onChange={event => onChange(event.target.value)}
      >
        <option value="">{copy.noCompare}</option>
        {candidates.filter(item => item.attemptId !== attemptId && item.outputFolder === workspace).map(item => (
          <option key={item.attemptId} value={item.attemptId}>{item.attemptId}</option>
        ))}
      </select>
    </label>
  )
}

function PlanStatus({ plan, preflight, copy }: { plan: ClonePlan | null; preflight: PreflightReport | null; copy: InspectorCopy }) {
  return (
    <>
      {plan ? (
        <p data-testid="inspector-plan" className="mt-2 text-[11px] text-text-secondary">
          {plan.kind === 'clone' ? copy.newIntent : copy.keptIntent}: {plan.intentId || copy.unknown}
        </p>
      ) : null}
      {preflight ? (
        <ul data-testid="inspector-preflight" className="mt-2 text-[11px]">
          <li className={preflight.ok ? 'text-emerald-300' : 'text-red-300'}>{preflight.ok ? copy.preflightOk : copy.preflightBlocked}</li>
          {preflight.issues.map((issue, index) => (
            <li key={`${issue.code}-${index}`} className={issue.blocking ? 'text-red-300' : 'text-amber-300'}>
              {warningText(copy, issue.code, issue.role, issue.field)}
            </li>
          ))}
        </ul>
      ) : null}
    </>
  )
}

export function GenerationInspectorDialog({
  open,
  onClose,
  attempt,
  workspace,
  catalog,
  currentModel,
  candidates = [],
  compareAttempt,
  onGenerate,
}: {
  open: boolean
  onClose: () => void
  attempt: InspectedAttempt
  workspace: string
  catalog?: CatalogItem[]
  currentModel?: CurrentModel
  candidates?: InspectedAttempt[]
  compareAttempt?: InspectedAttempt | null
  onGenerate?: (plan: ClonePlan, recipe: PortableRecipe) => Promise<string>
}) {
  const copy = inspectorCopy()
  const env = environment(workspace, catalog, currentModel)
  const [plan, setPlan] = useState<ClonePlan | null>(null)
  const [preflight, setPreflight] = useState<PreflightReport | null>(null)
  const [compareId, setCompareId] = useState(compareAttempt?.attemptId || '')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [seenId, setSeenId] = useState(attempt.attemptId)
  if (seenId !== attempt.attemptId) {
    setSeenId(attempt.attemptId)
    setPlan(null)
    setPreflight(null)
    setNote('')
  }
  const selectedCompare = pickCompare(compareAttempt, candidates, compareId, workspace)
  const diff = selectedCompare ? compareAttempts(attempt, selectedCompare) : null
  const allowed = attempt.outputFolder === workspace

  const applyPlan = (next: ClonePlan) => {
    if (busy) return
    setPlan(next)
    setPreflight(preflightGenerate(next, env))
    setNote('')
    setError('')
  }

  const handleRecipe = async () => {
    const recipe = copyRecipe(attempt, attempt.attemptId)
    await writeClipboard(JSON.stringify(recipe, null, 2))
    setNote(copy.recipeCopied)
  }

  const handleGenerate = async () => {
    if (!plan || !preflight?.ok || !onGenerate || busy) return
    setBusy(true); setError(''); setNote('')
    try {
      const task = await onGenerate(plan, copyRecipe(attempt, attempt.attemptId))
      setNote(`${copy.taskReady}: ${task}`)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure))
    } finally { setBusy(false) }
  }

  return (
    <ModalShell open={open && allowed} title={copy.title} onClose={onClose} className="fixed inset-0 z-[90] flex items-start justify-center overflow-auto bg-black/60 p-4">
      <div className="mt-8 w-[640px] max-w-[94vw] rounded-xl border border-border bg-bg-secondary p-5 text-text-primary shadow-2xl" onMouseDown={event => event.stopPropagation()}>
        <div className="mb-3 flex items-start justify-between gap-2">
          <div>
            <h2 className="text-sm font-semibold">{copy.title}</h2>
            <p className="text-[10px] text-text-muted">{copy.folder}: {attempt.outputFolder} · {copy.generationId}: {attempt.generationId || copy.unknown} · {copy.intent}: {displayField(attempt.intentId, copy.unknown)}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded border border-border px-2 py-1 text-[11px] text-text-secondary">{copy.close}</button>
        </div>
        {promptBox(copy.originalRequest, attempt.originalPrompt, copy.unknown)}
        <div className="mt-2">{promptBox(copy.effectivePrompt, attempt.effectivePrompt, copy.unknown)}</div>
        <section className="mt-3">
          <h3 className="text-[10px] uppercase tracking-wider text-text-muted">{copy.changes}</h3>
          <ChangeList changes={attempt.changes} copy={copy} />
        </section>
        <p className="mt-2 text-[11px] text-text-muted">{copy.model}: {displayField(attempt.model.id, copy.unknown)} · {copy.version}: {displayField(attempt.model.version, copy.unknown)}</p>
        <section className="mt-3">
          <h3 className="text-[10px] uppercase tracking-wider text-text-muted">{copy.refs}</h3>
          <RefList refs={attempt.refs} copy={copy} />
        </section>
        <section className="mt-3">
          <CompareSelect copy={copy} compareId={compareId} candidates={candidates} attemptId={attempt.attemptId} workspace={workspace} onChange={setCompareId} />
          {diff ? <DiffList diff={diff} copy={copy} /> : null}
        </section>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" onClick={() => applyPlan(planClone(attempt, env))} className="rounded border border-accent-blue/40 px-2 py-1 text-[11px] text-accent-blue">{copy.clone}</button>
          <button type="button" onClick={() => applyPlan(planRetry(attempt, env))} className="rounded border border-border px-2 py-1 text-[11px] text-text-secondary">{copy.retry}</button>
          <button type="button" onClick={() => { void handleRecipe() }} className="rounded border border-border px-2 py-1 text-[11px] text-text-secondary">{copy.copyRecipe}</button>
          <button type="button" disabled={!preflight?.ok || !onGenerate || busy} onClick={() => void handleGenerate()} className="rounded border border-emerald-400/40 px-2 py-1 text-[11px] text-emerald-300 disabled:opacity-40">{copy.generate}</button>
        </div>
        <PlanStatus plan={plan} preflight={preflight} copy={copy} />
        {note ? <p role="status" className="mt-2 text-[11px] text-emerald-300">{note}</p> : null}
        {error ? <p role="alert" className="mt-2 text-[11px] text-red-300">{error}</p> : null}
      </div>
    </ModalShell>
  )
}
