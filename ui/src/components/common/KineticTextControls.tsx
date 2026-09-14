import { useUiTranslation } from '../../i18n'
import { KINETIC_PRESETS, parseKineticTexts, type KineticText } from '../../lib/kineticText'
import { randomUuid } from '../../lib/uuid'

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
        <label className="block text-xs">{t('text')}<textarea maxLength={240} value={cue.text} onChange={event => update(cue.id, { text: event.target.value })} className="mt-1 w-full rounded border border-border bg-bg-tertiary p-2 text-sm" /></label>
        <div className="flex flex-wrap gap-3">
          <label className="text-xs">{t('preset')}<select value={cue.preset} onChange={event => update(cue.id, { preset: event.target.value as KineticText['preset'] })} className="ml-2 rounded border border-border bg-bg-tertiary p-2">{KINETIC_PRESETS.map(preset => <option key={preset} value={preset}>{t(`presets.${preset}`)}</option>)}</select></label>
          <label className="flex items-center gap-2 text-xs">{t('color')}<input type="color" value={cue.color} onChange={event => update(cue.id, { color: event.target.value })} /></label>
          <label className="text-xs">{t('font')}<select value={cue.font ?? 'sans'} onChange={event => update(cue.id, { font: event.target.value as KineticText['font'] })} className="ml-2 rounded border border-border bg-bg-tertiary p-2"><option value="sans">{t('fonts.sans')}</option><option value="mono">{t('fonts.mono')}</option></select></label>
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
          {(['start', 'end', 'x', 'y', 'size', 'rotation'] as const).map(key => <label key={key} className="text-xs">{t(key)}<input type="number" step={key === 'start' || key === 'end' ? .1 : 1} value={cue[key]} onChange={event => { const value = event.target.valueAsNumber; if (Number.isFinite(value) && (key !== 'end' || value > cue.start) && (key !== 'start' || value < cue.end)) update(cue.id, { [key]: value }) }} className="mt-1 min-h-9 w-full rounded border border-border bg-bg-tertiary px-2" /></label>)}
        </div>
        <button type="button" onClick={() => onChange(cues.filter(item => item.id !== cue.id))} className="min-h-9 text-xs text-red-300">{t('remove')}</button>
      </div>)}
      <button type="button" disabled={cues.length >= 12} onClick={() => onChange([...cues, ...parseKineticTexts([{ id: randomUuid(), text: t('defaultText'), start: 0, end: Math.min(3, duration), preset: 'impact' }])])} className="min-h-10 rounded border border-cyan-400/40 px-3 text-xs text-cyan-200 disabled:opacity-40">{t('add')}</button>
    </fieldset>
  </details>
}
