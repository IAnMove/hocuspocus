import { useUiTranslation } from '../../i18n'
import { parseKineticTexts, type KineticText } from '../../lib/kineticText'
import { randomUuid } from '../../lib/uuid'
import { TextCueBox, TextCueContent, TextCueMotion, TextCuePreview, TextCueStyle } from './kineticText/TextCueSections'

const MAX_CUES = 48

export function KineticTextControls({ cues = [], duration, disabled, onChange }: {
  cues?: KineticText[]; duration: number; disabled?: boolean; onChange: (cues: KineticText[]) => void
}) {
  const { t } = useUiTranslation('kineticText')
  const update = (id: string, patch: Partial<KineticText>) => onChange(parseKineticTexts(cues.map(cue => cue.id === id ? { ...cue, ...patch } : cue)))
  return <details className="rounded-lg border border-border bg-bg-primary p-3">
    <summary className="cursor-pointer text-sm font-semibold text-text-primary">{t('title')} ({cues.length})</summary>
    <p className="my-2 text-xs text-text-muted">{t('help')}</p>
    <fieldset disabled={disabled} className="space-y-3 disabled:opacity-50">
      {cues.map(cue => <div key={cue.id} className="space-y-2 rounded border border-border p-2">
        <TextCuePreview cue={cue} />
        <TextCueContent cue={cue} update={patch => update(cue.id, patch)} />
        <TextCueStyle cue={cue} update={patch => update(cue.id, patch)} />
        <TextCueMotion cue={cue} update={patch => update(cue.id, patch)} />
        <TextCueBox cue={cue} update={patch => update(cue.id, patch)} />
        <button type="button" onClick={() => onChange(cues.filter(item => item.id !== cue.id))} className="min-h-9 text-xs text-red-300">{t('remove')}</button>
      </div>)}
      <button type="button" disabled={cues.length >= MAX_CUES} onClick={() => onChange([...cues, ...parseKineticTexts([{ id: randomUuid(), text: t('defaultText'), start: 0, end: Math.min(3, duration), preset: 'impact' }])])} className="min-h-10 rounded border border-cyan-400/40 px-3 text-xs text-cyan-200 disabled:opacity-40">{t('add')}</button>
    </fieldset>
  </details>
}
