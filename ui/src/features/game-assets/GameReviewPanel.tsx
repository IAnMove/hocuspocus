import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { codeLabel } from './gameErrors'
import { approvableClean, attemptWarnings, metricLines, reviewAssets, type ReviewWarning } from './reviewModel'
import { AttemptPreview } from './reviewViews'
import { useGameAssetsStore } from './store'
import { buttonClass, fieldClass, panelClass } from './styles'
import type { GameAsset, GameAttempt } from './types'

export function GameReviewPanel() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const approveClean = useGameAssetsStore(state => state.approveClean)
  const [kind, setKind] = useState('')
  const listed = reviewAssets(game?.assets || [], '')
  const assets = kind ? listed.filter(asset => asset.kind === kind) : listed
  const kinds = [...new Set(listed.map(asset => asset.kind))]
  const clean = approvableClean(game?.assets || [])

  const approveAll = () => {
    if (!clean.length || !window.confirm(t('confirmApproveClean', { count: clean.length }))) return
    void approveClean()
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <select aria-label={t('kind')} className={`${fieldClass} w-auto`} value={kind} onChange={event => setKind(event.target.value)}>
          <option value="">{t('allKinds')}</option>
          {kinds.map(item => <option key={item} value={item}>{codeLabel('kinds', item)}</option>)}
        </select>
        <button type="button" className={buttonClass} disabled={!clean.length} onClick={approveAll}>{t('approveClean')}</button>
      </div>
      {!assets.length && <p className="text-sm text-muted-foreground">{t('reviewEmpty')}</p>}
      <div className="grid gap-3">
        {assets.map(asset => <ReviewCard key={asset.id} asset={asset} pixel={Boolean(game?.style.pixel.enabled)} />)}
      </div>
    </div>
  )
}

function ReviewCard({ asset, pixel }: { asset: GameAsset; pixel: boolean }) {
  const { t } = useUiTranslation('gameAssets')
  const workspace = useGameAssetsStore(state => state.workspace)
  const setLock = useGameAssetsStore(state => state.setLock)
  const regenerateAsset = useGameAssetsStore(state => state.regenerateAsset)
  return (
    <article className={panelClass}>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <span>{codeLabel('kinds', asset.kind)}</span>
        <span className="font-mono">{asset.id}</span>
        <span>{asset.name}</span>
        <span>{codeLabel('statuses', asset.status)}</span>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {asset.attempts.map(attempt => <AttemptCard key={attempt.id} asset={asset} attempt={attempt} pixel={pixel} workspace={workspace} />)}
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" className={buttonClass} aria-label={t('regenerateFor', { id: asset.id })} onClick={() => { void regenerateAsset(asset.id) }}>{t('regenerateOne')}</button>
        <button type="button" className={buttonClass} aria-label={t(asset.locked ? 'unlockFor' : 'lockFor', { id: asset.id })}
          onClick={() => { void setLock(asset.id, !asset.locked) }}>{asset.locked ? t('unlockAsset') : t('lockAsset')}</button>
      </div>
    </article>
  )
}

function warningLabel(warning: ReviewWarning): string {
  const text = codeLabel('warnings', warning.code, warning.message || warning.code, { id: warning.ref })
  return warning.file ? `${text} (${warning.file})` : text
}

function decisionLabel(attempt: GameAttempt): 'decisions.failed' | 'decisions.approved' | 'decisions.rejected' | 'decisions.undecided' {
  if (attempt.status !== 'ok') return 'decisions.failed'
  if (attempt.decision === 'approved') return 'decisions.approved'
  if (attempt.decision === 'rejected') return 'decisions.rejected'
  return 'decisions.undecided'
}

function AttemptCard({ asset, attempt, pixel, workspace }: { asset: GameAsset; attempt: GameAttempt; pixel: boolean; workspace: string }) {
  const { t } = useUiTranslation('gameAssets')
  const approveAttempt = useGameAssetsStore(state => state.approveAttempt)
  const rejectAttempt = useGameAssetsStore(state => state.rejectAttempt)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const warnings = attemptWarnings(attempt)
  const approvable = attempt.status === 'ok' && attempt.decision !== 'approved'
  const decide = async (action: () => Promise<boolean>, clearNote: boolean) => {
    setBusy(true)
    const done = await action()
    setBusy(false)
    if (done && clearNote) setNote('')
  }
  return (
    <section className="space-y-2 rounded-md border border-border p-2" aria-label={t('candidate', { id: attempt.id })}>
      <p className="text-sm"><span className="font-mono">{attempt.id}</span> · {t(decisionLabel(attempt))}</p>
      {attempt.note && <p className="text-sm text-muted-foreground">{t('decisionNote', { note: attempt.note })}</p>}
      <AttemptPreview asset={asset} attempt={attempt} pixel={pixel} workspace={workspace} />
      {metricLines(attempt.metrics).map(line => <p key={line} className="text-sm">{line}</p>)}
      {warnings.length === 0 && <p className="text-sm">{t('noWarnings')}</p>}
      {warnings.map(warning => <p key={warning.key} className="text-sm text-amber-500">{warningLabel(warning)}</p>)}
      <textarea aria-label={t('rejectNoteFor', { id: attempt.id })} className={fieldClass} value={note} onChange={event => setNote(event.target.value)} placeholder={t('rejectNote')} />
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} disabled={busy || !approvable} aria-label={t('approveCandidate', { id: attempt.id })}
          onClick={() => { void decide(() => approveAttempt(asset.id, attempt.id), false) }}>{t('approveAttempt')}</button>
        <button type="button" className={buttonClass} disabled={busy || !note.trim()} aria-label={t('rejectCandidate', { id: attempt.id })}
          onClick={() => { void decide(() => rejectAttempt(asset.id, attempt.id, note.trim()), true) }}>{t('rejectAttempt')}</button>
      </div>
    </section>
  )
}
