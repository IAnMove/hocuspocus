import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { gameText } from './gameErrors'
import { ErrorNotice, EstimateSummary, ProblemList } from './gameUi'
import { EXAMPLE_LIST, LIST_FORMATS, listBody, readEstimate, removedByReplace, type ListFormat } from './listModel'
import { useGameAssetsStore, type ListBodyInput, type ListOutcome } from './store'
import { buttonClass, fieldClass, panelClass } from './styles'
import type { GameAsset, GameProblem, ListReport } from './types'

/** ``N assets will be removed`` and the approved or locked ones by name. */
function replaceMessage(removed: GameAsset[]): string {
  const kept = removed.filter(asset => asset.status === 'approved' || asset.locked)
  const lines = [gameText('replaceRemoves', { count: removed.length })]
  if (kept.length) lines.push(gameText('replaceRemovesKept', { names: kept.map(asset => asset.name || asset.id).join(', ') }))
  return lines.join('\n')
}

export function GameListPasteDialog({ onClose }: { onClose: () => void }) {
  const { t } = useUiTranslation('gameAssets')
  const assets = useGameAssetsStore(state => state.game?.assets)
  const previewList = useGameAssetsStore(state => state.previewList)
  const commitList = useGameAssetsStore(state => state.commitList)
  const [text, setText] = useState('')
  const [format, setFormat] = useState<ListFormat>('lines')
  const [replace, setReplace] = useState(false)
  const [report, setReport] = useState<ListReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [failure, setFailure] = useState<{ error: string; problems: GameProblem[] } | null>(null)

  // Any change to the list, its format or the replace flag needs a new check.
  const reset = () => {
    setReport(null)
    setFailure(null)
  }

  const send = async (action: (body: ListBodyInput) => Promise<ListOutcome>): Promise<ListOutcome | null> => {
    const body = listBody(text, format)
    if (!body) {
      setFailure({ error: t('errors.invalid_json'), problems: [] })
      return null
    }
    setBusy(true)
    setFailure(null)
    const outcome = await action({ ...body, replace })
    setBusy(false)
    if (!outcome.ok) setFailure({ error: outcome.error, problems: outcome.problems })
    return outcome
  }

  const check = async () => {
    const outcome = await send(previewList)
    if (outcome?.ok) setReport(outcome.report)
  }

  const add = async () => {
    const removed = replace && report ? removedByReplace(assets || [], report.items) : []
    if (removed.length && !window.confirm(replaceMessage(removed))) return
    const outcome = await send(commitList)
    if (outcome?.ok) onClose()
  }

  const readFile = async (input: HTMLInputElement, next: ListFormat) => {
    const file = input.files?.[0]
    input.value = '' // the same file can be imported again
    if (!file) return
    setText(await file.text())
    setFormat(next)
    reset()
  }

  const problems = report?.problems || []
  const ready = Boolean(report) && !problems.length
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-modal="true" aria-label={t('paste')}>
      <div className={`${panelClass} max-h-[90vh] w-full max-w-2xl space-y-3 overflow-y-auto`}>
        <textarea aria-label={t('listText')} placeholder={EXAMPLE_LIST} className={`${fieldClass} min-h-40 font-mono`} value={text}
          onChange={event => { setText(event.target.value); reset() }} />
        <div className="flex flex-wrap items-center gap-2">
          <label className="text-sm">
            {t('listFormat')}
            <select aria-label={t('listFormat')} className={`${fieldClass} ml-2 w-auto`} value={format}
              onChange={event => { setFormat(event.target.value as ListFormat); reset() }}>
              {LIST_FORMATS.map(item => <option key={item} value={item}>{t(`listFormats.${item}`)}</option>)}
            </select>
          </label>
          <label className={buttonClass}>{t('importCsv')}<input className="sr-only" type="file" accept=".csv,text/csv" onChange={event => { void readFile(event.currentTarget, 'csv') }} /></label>
          <label className={buttonClass}>{t('importJson')}<input className="sr-only" type="file" accept=".json,application/json" onChange={event => { void readFile(event.currentTarget, 'json') }} /></label>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={replace} onChange={event => { setReplace(event.target.checked); reset() }} />
          {t('replaceList')}
        </label>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={buttonClass} disabled={busy || !text.trim()} onClick={() => { void check() }}>{t('checkList')}</button>
          <button type="button" className={buttonClass} disabled={busy || !ready} onClick={() => { void add() }}>{replace ? t('replaceListAction') : t('addList')}</button>
          <button type="button" className={buttonClass} onClick={onClose}>{t('close')}</button>
        </div>
        <ErrorNotice error={failure?.error} problems={failure?.problems} />
        {report && !problems.length && <p className="text-sm">{t('noProblems')}</p>}
        <ProblemList problems={problems} />
        {report && <EstimateSummary estimate={readEstimate(report.estimate)} />}
      </div>
    </div>
  )
}
