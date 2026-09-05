import { ChevronDown, ChevronUp, Trash2 } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import { moveItem } from './storyLabEditors'
import { button, input, Field } from './storyLabChrome'
import type { StoryBeat, StoryProject } from './types'

export function CompactBeatEditor({ beat, index, total, update }: {
  beat: StoryBeat
  index: number
  total: number
  update: (updater: (project: StoryProject) => StoryProject) => void
}) {
  const { t } = useUiTranslation('storyLab')
  const set = (change: Partial<StoryBeat>) => update(current => {
    current.beats = current.beats.map(item => item.id === beat.id ? { ...item, ...change } : item)
    return current
  })
  return (
    <div className="rounded-lg border border-border bg-bg-tertiary/35 p-2.5 space-y-2">
      <div className="flex items-center gap-2">
        <span className="w-5 shrink-0 text-sm font-bold text-text-muted/60">{index + 1}</span>
        <input className={input} value={beat.title} onChange={event => set({ title: event.target.value })} placeholder={t('compact.momentName')} aria-label={t('compact.momentAria', { index: index + 1 })} />
        <button className={button} disabled={index === 0} title={t('compact.moveUp')} onClick={() => update(current => { moveItem(current.beats, index, index - 1); return current })}><ChevronUp size={12} /></button>
        <button className={button} disabled={index === total - 1} title={t('compact.moveDown')} onClick={() => update(current => { moveItem(current.beats, index, index + 1); return current })}><ChevronDown size={12} /></button>
        <button className="p-1 text-red-400" title={t('compact.remove')} onClick={() => update(current => { current.beats = current.beats.filter(item => item.id !== beat.id); return current })}><Trash2 size={12} /></button>
      </div>
      <Field label={t('compact.whatWeSee')} value={beat.summary} onChange={summary => set({ summary })} rows={3} />
      <div className="grid sm:grid-cols-2 gap-2">
        <Field label={t('compact.tension')} value={beat.conflict} onChange={conflict => set({ conflict })} rows={2} />
        <Field label={t('compact.nextCutChange')} value={beat.turn} onChange={turn => set({ turn })} rows={2} />
      </div>
      <details className="rounded border border-border px-2 py-1.5 text-[10px] text-text-muted">
        <summary className="cursor-pointer text-text-secondary">{t('compact.optionalSection')}</summary>
        <div className="mt-2 grid sm:grid-cols-2 gap-2">
          <Field label={t('compact.sectionOrPhase')} value={beat.stage} onChange={stage => set({ stage })} />
          <Field label={t('compact.momentGoal')} value={beat.goal} onChange={goal => set({ goal })} rows={2} />
        </div>
      </details>
    </div>
  )
}
