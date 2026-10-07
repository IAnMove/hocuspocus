import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { approvableClean, attemptWarnings, metricLines, reviewAssets } from './reviewModel'
import { AttemptPreview } from './reviewViews'
import { useGameAssetsStore } from './store'
import { buttonClass, fieldClass, panelClass } from './styles'
import type { GameAsset, GameAttempt } from './types'

export function GameReviewPanel() {
  const { t } = useUiTranslation('gameAssets')
  const game = useGameAssetsStore(state => state.game)
  const approveClean = useGameAssetsStore(state => state.approveClean)
  const [kind, setKind] = useState('')
  const assets = reviewAssets(game?.assets || [], kind)
  const kinds = [...new Set((game?.assets || []).filter(asset => asset.status === 'review').map(asset => asset.kind))]
  const clean = approvableClean(game?.assets || [])

  const approveAll = () => {
    if (!clean.length || !window.confirm(t('confirmApproveClean'))) return
    void approveClean()
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        <select aria-label={t('kind')} className={`${fieldClass} w-auto`} value={kind} onChange={event => setKind(event.target.value)}>
          <option value="">{t('allKinds')}</option>
          {kinds.map(item => <option key={item} value={item}>{item}</option>)}
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
        <span>{asset.kind}</span>
        <span className="font-mono">{asset.id}</span>
        <span>{asset.name}</span>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {asset.attempts.map(attempt => <AttemptCard key={attempt.id} asset={asset} attempt={attempt} pixel={pixel} workspace={workspace} />)}
      </div>
      <div className="mt-2 flex flex-wrap gap-2">
        <button type="button" className={buttonClass} onClick={() => { void regenerateAsset(asset.id) }}>{t('regenerateOne')}</button>
        <button type="button" className={buttonClass} onClick={() => { void setLock(asset.id, !asset.locked) }}>{asset.locked ? t('unlockAsset') : t('lockAsset')}</button>
      </div>
    </article>
  )
}

function AttemptCard({ asset, attempt, pixel, workspace }: { asset: GameAsset; attempt: GameAttempt; pixel: boolean; workspace: string }) {
  const { t } = useUiTranslation('gameAssets')
  const approveAttempt = useGameAssetsStore(state => state.approveAttempt)
  const rejectAttempt = useGameAssetsStore(state => state.rejectAttempt)
  const [note, setNote] = useState('')
  const warnings = attemptWarnings(attempt)
  return (
    <div className="space-y-2 rounded-md border border-border p-2">
      <AttemptPreview asset={asset} attempt={attempt} pixel={pixel} workspace={workspace} />
      {metricLines(attempt.metrics).map(line => <p key={line} className="text-sm">{line}</p>)}
      {warnings.length === 0 && <p className="text-sm">{t('noWarnings')}</p>}
      {warnings.map(code => <p key={code} className="text-sm">{warningText(code, t('warnLoopSeam'), t('warnDuplicate', { id: code.startsWith('duplicate_of:') ? code.slice('duplicate_of:'.length) : '' }))}</p>)}
      <textarea aria-label={`${t('rejectNote')} ${attempt.id}`} className={fieldClass} value={note} onChange={event => setNote(event.target.value)} placeholder={t('rejectNote')} />
      <div className="flex flex-wrap gap-2">
        <button type="button" className={buttonClass} onClick={() => { void approveAttempt(asset.id, attempt.id) }}>{t('approveAttempt')}</button>
        <button type="button" className={buttonClass} disabled={!note.trim()} onClick={() => { void rejectAttempt(asset.id, attempt.id, note.trim()) }}>{t('rejectAttempt')}</button>
      </div>
    </div>
  )
}

function warningText(code: string, seam: string, duplicate: string): string {
  if (code === 'loop_seam') return seam
  if (code.startsWith('duplicate_of:')) return duplicate
  return code
}
