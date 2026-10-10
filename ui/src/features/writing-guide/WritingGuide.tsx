import { useEffect, useRef, useState } from 'react'
import { useUiTranslation } from '../../i18n'
import { proposeWriting, type GuideProvider } from './api'
import { applyChanges, catalog, undoChanges, type GuideAction, type GuideData, type GuideScope, type GuideUpdate } from './model'
import { WritingProposal } from './WritingProposal'
import { WritingAnswer } from './WritingAnswer'
import { guideButton, guideInput } from './styles'

export type WritingGuideProps = {
  scope: GuideScope; data: GuideData; language: string; context: Record<string, unknown>
  provider: GuideProvider; onChange: (update: GuideUpdate) => void
}

/** The owner keys this component by workspace/project/entity. A proposal never applies itself. */
export function WritingGuide({ scope, data, language, context, provider, onChange }: WritingGuideProps) {
  const { t, i18n } = useUiTranslation('writingGuide')
  const uiLanguage = i18n.language.startsWith('es') ? 'es' : 'en'
  const [advanced, setAdvanced] = useState(false)
  const [position, setPosition] = useState(0)
  const [busy, setBusy] = useState<GuideAction | null>(null)
  const [error, setError] = useState('')
  const controller = useRef<AbortController | null>(null)
  useEffect(() => () => { controller.current?.abort() }, [])
  const fields = catalog.scopes[scope]
  const visible = fields.filter(field => advanced || !field.advanced)
  const index = Math.min(position, visible.length - 1)
  const field = visible[index]
  const question = catalog.questions[field.id]
  const answered = fields.filter(item => data.values[item.id]?.trim()).length
  const pending = data.section.pending
  const undo = data.section.undo
  const canUndo = Boolean(undo && Object.keys(undo.after).every(key => data.values[key] === undo.after[key]))
  const summary = fields.map(item => data.values[item.id]).filter(Boolean).slice(0, 2).join(' · ')

  const run = async (action: GuideAction) => {
    if (controller.current) return
    const abort = new AbortController()
    controller.current = abort
    setBusy(action); setError('')
    const base = { ...data.values }
    try {
      const result = await proposeWriting({ scope, action, questionId: field.id, language, values: base, context, provider }, abort.signal)
      if (abort.signal.aborted) return
      onChange(current => ({ ...current, section: { ...current.section, pending: {
        ...result, action, questionId: field.id, base, createdAt: new Date().toISOString(),
        selected: result.suggestions.filter(row => !base[row.field]?.trim()).map(row => row.field),
      } } }))
    } catch (reason) {
      if (!abort.signal.aborted) setError(reason instanceof Error ? reason.message : t('failed'))
    } finally {
      if (controller.current === abort) { controller.current = null; setBusy(null) }
    }
  }
  const apply = () => onChange(current => {
    const p = current.section.pending
    if (!p) return current
    return applyChanges(current, p.base, Object.fromEntries(p.suggestions
      .filter(row => p.selected.includes(row.field)).map(row => [row.field, row.value])))
  })
  return <details className="my-3 min-w-0 rounded-xl border border-border bg-bg-secondary p-3 md:p-4" data-testid="writing-guide">
    <summary className="cursor-pointer text-sm text-text-primary">
      <span className="font-medium">{t('open')} · {t(`scope.${scope}`)}</span>
      <span className="ml-2 text-xs text-text-muted">{t('progress', { answered, total: fields.length })}{pending ? ` · ${t('proposalReady')}` : ''}</span>
      {summary && <span className="mt-1 block truncate text-xs text-text-muted">{summary.slice(0, 220)}</span>}
    </summary>
    <div className="mt-4 space-y-4">
      <p className="text-xs leading-relaxed text-text-muted">{t('intro')}</p>
      <div className="flex flex-wrap items-center gap-2">
        <select aria-label={t('chooseQuestion')} className={`${guideInput} flex-1`} value={field.id}
          onChange={event => setPosition(visible.findIndex(item => item.id === event.target.value))}>
          {visible.map((item, i) => <option key={item.id} value={item.id}>{i + 1}. {catalog.questions[item.id].question[uiLanguage]}</option>)}
        </select>
        {fields.some(item => item.advanced) && <label className="flex items-center gap-2 text-xs text-text-secondary">
          <input type="checkbox" checked={advanced} onChange={event => { setAdvanced(event.target.checked); setPosition(0) }} />{t('deeper')}
        </label>}
      </div>
      <WritingAnswer key={field.id} question={question.question[uiLanguage]} hint={question.hint[uiLanguage]}
        value={data.values[field.id] || ''} placeholder={t('answerPlaceholder')}
        onChange={value => onChange(current => ({ ...current, values: { ...current.values, [field.id]: value } }))} />
      <p className="whitespace-pre-wrap text-xs text-text-muted">{t('example')}: {question.example[uiLanguage]}</p>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={guideButton} disabled={index === 0} onClick={() => setPosition(index - 1)}>{t('previous')}</button>
        <button type="button" className={guideButton} disabled={index === visible.length - 1} onClick={() => setPosition(index + 1)}>{t('next')}</button>
        <button type="button" className={guideButton} disabled={Boolean(busy || pending)} onClick={() => void run('examples')}>{t('examples')}</button>
      </div>
      <div className="flex flex-wrap gap-2 border-t border-border pt-3">
        <button type="button" className={guideButton} disabled={Boolean(busy || pending) || answered === fields.length} onClick={() => void run('fill')}>{t('fill')}</button>
        <button type="button" className={guideButton} disabled={Boolean(busy || pending)} onClick={() => void run('develop')}>{t('develop')}</button>
        <button type="button" className={guideButton} disabled={Boolean(busy || pending) || !answered} onClick={() => void run('review')}>{t('review')}</button>
        <button type="button" className={guideButton} disabled={!canUndo || Boolean(busy)} onClick={() => onChange(undoChanges)}>{t('undo')}</button>
      </div>
      {busy && <div role="status" className="flex items-center gap-2 text-sm text-text-secondary">
        {t('working')}<button type="button" className={guideButton} onClick={() => {
          controller.current?.abort(); controller.current = null; setBusy(null)
        }}>{t('cancel')}</button>
      </div>}
      {error && <p role="alert" className="text-sm text-red-500">{error}</p>}
      <WritingProposal data={data} onChange={onChange} onApply={apply} />
    </div>
  </details>
}
