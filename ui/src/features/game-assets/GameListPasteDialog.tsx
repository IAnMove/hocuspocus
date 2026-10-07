import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { useGameAssetsStore } from './store'
import { buttonClass, fieldClass, panelClass } from './styles'
import { EXAMPLE_LIST, estimateSource, listBody, readEstimate } from './listModel'
import type { GameEstimate, ListProblem } from './types'

export function GameListPasteDialog({ onClose }: { onClose: () => void }) {
  const { t } = useUiTranslation('gameAssets')
  const previewList = useGameAssetsStore(state => state.previewList)
  const commitList = useGameAssetsStore(state => state.commitList)
  const [text, setText] = useState(EXAMPLE_LIST)
  const [format, setFormat] = useState<'lines' | 'csv' | 'json'>('lines')
  const [replace, setReplace] = useState(false)
  const [problems, setProblems] = useState<ListProblem[] | null>(null)
  const [estimate, setEstimate] = useState<GameEstimate | null>(null)
  const [busy, setBusy] = useState(false)
  const [localError, setLocalError] = useState('')

  const body = () => listBody(text, format)

  const check = async () => {
    setBusy(true)
    setLocalError('')
    try {
      const report = await previewList(body())
      setProblems(report.problems || [])
      setEstimate(readEstimate(report.estimate))
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'Could not check the list')
    } finally {
      setBusy(false)
    }
  }

  const add = async () => {
    setBusy(true)
    setLocalError('')
    try {
      const report = await commitList({ ...body(), replace })
      setProblems(report.problems || [])
      if (!report.problems?.length) onClose()
    } catch (error) {
      setLocalError(error instanceof Error ? error.message : 'Could not add the list')
    } finally {
      setBusy(false)
    }
  }

  const readFile = async (file: File | undefined, next: 'csv' | 'json') => {
    if (!file) return
    setText(await file.text())
    setFormat(next)
    setProblems(null)
  }

  const source = estimate ? estimateSource(estimate.source) : 'defaults'
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/60 p-4" role="dialog" aria-label={t('paste')}>
      <div className={`${panelClass} max-h-[90vh] w-full max-w-2xl space-y-3 overflow-y-auto`}>
        <textarea aria-label={t('example')} className={`${fieldClass} min-h-40 font-mono`} value={text} onChange={event => { setText(event.target.value); setFormat('lines'); setProblems(null) }} />
        <div className="flex flex-wrap gap-2">
          <label className={buttonClass}>{t('importCsv')}<input className="sr-only" type="file" accept=".csv,text/csv" onChange={event => { void readFile(event.target.files?.[0], 'csv') }} /></label>
          <label className={buttonClass}>{t('importJson')}<input className="sr-only" type="file" accept=".json,application/json" onChange={event => { void readFile(event.target.files?.[0], 'json') }} /></label>
          <button type="button" className={buttonClass} disabled={busy} onClick={() => { void check() }}>{t('checkList')}</button>
          <button type="button" className={buttonClass} disabled={busy || !problems || problems.length > 0} onClick={() => { void add() }}>{t('addList')}</button>
          <button type="button" className={buttonClass} onClick={onClose}>{t('close')}</button>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={replace} onChange={event => setReplace(event.target.checked)} />
          {t('replaceList')}
        </label>
        {localError && <p className="text-sm text-red-500">{localError}</p>}
        {problems && !problems.length && <p className="text-sm">{t('noProblems')}</p>}
        {problems?.map((problem, index) => (
          <p key={`${problem.line}-${problem.code}-${index}`} className="text-sm text-red-500">{t('problemLine', { line: problem.line || 0, message: problem.message || problem.code || '' })}</p>
        ))}
        {estimate && (
          <div className="text-sm">
            <p>{t('estimate', { minutes: estimate.minutes })} · {source === 'history' ? t('sourceHistory') : source === 'trial' ? t('sourceTrial') : t('sourceDefaults')}</p>
            {Object.entries(estimate.byKind).map(([kind, minutes]) => <p key={kind}>{kind}: {minutes}</p>)}
          </div>
        )}
      </div>
    </div>
  )
}
