import { useUiTranslation } from '../../i18n'
import { MAX_ANSWER, catalog, type GuideData, type GuideUpdate } from './model'
import { guideButton, guideInput } from './styles'

export function WritingProposal({ data, onChange, onApply }: {
  data: GuideData; onChange: (update: GuideUpdate) => void; onApply: () => void
}) {
  const { t, i18n } = useUiTranslation('writingGuide')
  const language = i18n.language.startsWith('es') ? 'es' : 'en'
  const pending = data.section.pending
  if (!pending) return null
  const stale = pending.selected.some(key => data.values[key] !== pending.base[key])
  const edit = (field: string, value: string) => onChange(current => {
    const proposal = current.section.pending
    return proposal ? { ...current, section: { ...current.section, pending: { ...proposal,
      suggestions: proposal.suggestions.map(row => row.field === field ? { ...row, value } : row) } } } : current
  })
  const select = (field: string, checked: boolean) => onChange(current => {
    const proposal = current.section.pending
    return proposal ? { ...current, section: { ...current.section, pending: { ...proposal,
      selected: checked ? [...new Set([...proposal.selected, field])] : proposal.selected.filter(key => key !== field) } } } : current
  })
  return <div className="space-y-3 rounded-lg border border-border bg-bg-primary p-3" data-testid="writing-proposal">
    <p className="text-sm font-medium text-text-primary">{t('proposal')}</p>
    {pending.examples.map((example, index) => <div key={index} className="space-y-2 rounded-lg border border-border p-3">
      <p className="whitespace-pre-wrap text-sm text-text-secondary">{example}</p>
      <button type="button" className={guideButton} onClick={() => onChange(current => {
        const p = current.section.pending
        return p ? { ...current, section: { ...current.section, pending: { ...p,
          suggestions: [{ field: p.questionId, value: example, reason: t('exampleProposal') }],
          selected: current.values[p.questionId] ? [] : [p.questionId] } } } : current
      })}>{t('useExample')}</button>
    </div>)}
    {pending.suggestions.map(row => {
      const question = catalog.questions[row.field]?.question[language] || row.field
      return <div key={row.field} className="space-y-2 border-t border-border pt-3">
        <label className="flex items-start gap-2 text-sm text-text-primary">
          <input type="checkbox" checked={pending.selected.includes(row.field)} onChange={event => select(row.field, event.target.checked)} />
          {t('include', { question })}
        </label>
        {data.values[row.field] && <p className="whitespace-pre-wrap text-xs text-text-muted">{t('current')}: {data.values[row.field]}</p>}
        <textarea aria-label={t('proposed', { question })} className={guideInput} rows={4} maxLength={MAX_ANSWER}
          value={row.value} onChange={event => edit(row.field, event.target.value)} />
        {row.reason && <p className="text-xs text-text-muted">{row.reason}</p>}
      </div>
    })}
    {pending.review.length > 0 && <div className="space-y-3" aria-label={t('review')}>
      <p className="text-xs text-text-muted">{t('reviewHint')}</p>
      {pending.review.map((row, index) => <div key={index} className="rounded-lg border border-border p-3 text-sm">
        <p className="font-medium text-text-primary">{catalog.questions[row.field]?.question[language]}</p>
        <p className="mt-1 text-text-secondary">{row.issue}</p>
        <p className="mt-1 text-text-secondary">{row.suggestion}</p>
      </div>)}
    </div>}
    {!pending.suggestions.length && !pending.examples.length && !pending.review.length && <p className="text-sm text-text-muted">{t('noSuggestions')}</p>}
    {stale && <p role="alert" className="text-sm text-amber-500">{t('stale')}</p>}
    <div className="flex flex-wrap gap-2">
      {!!pending.suggestions.length && <button type="button" className={guideButton} disabled={!pending.selected.length || stale} onClick={onApply}>{t('apply')}</button>}
      <button type="button" className={guideButton} onClick={() => onChange(current => ({
        ...current, section: { ...current.section, pending: undefined },
      }))}>{t('discard')}</button>
    </div>
    <p className="text-xs text-text-muted">{pending.provider} {pending.model} · {pending.usage
      ? t('usage', { prompt: pending.usage.prompt_tokens, completion: pending.usage.completion_tokens })
      : t('usageUnknown')}</p>
  </div>
}
