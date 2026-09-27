import { useUiTranslation } from '../../i18n'
import { FX_CATALOG, parseSceneFx, type SceneFx } from './types'

export function SceneFxControls({ cues = [], duration, disabled, onChange, onShowcase }: {
  cues?: SceneFx[]; duration: number; disabled?: boolean; onChange: (cues: SceneFx[]) => void; onShowcase: (collection?: 'all' | 'anime' | 'retro') => void
}) {
  const { t } = useUiTranslation('sceneFx')
  const update = (id: string, patch: Partial<SceneFx>) => onChange(parseSceneFx(cues.map(cue => cue.id === id ? { ...cue, ...patch } : cue)))
  const collections = ['classic', 'anime', 'retro'] as const
  return <details className="rounded-lg border border-border bg-bg-primary p-3" data-testid="scene-fx-controls">
    <summary className="cursor-pointer text-sm font-semibold">{t('title')} ({cues.length})</summary>
    <p className="my-2 text-xs text-text-muted">{t('help')}</p>
    <fieldset disabled={disabled} className="space-y-3 disabled:opacity-50">
      {cues.map(cue => <div key={cue.id} className="space-y-2 rounded border border-border p-2">
        <div className="flex flex-wrap items-center gap-3">
          <label>{t('effect')}<select value={cue.kind} onChange={e => update(cue.id, { kind: e.target.value, color: FX_CATALOG.find(item => item.id === e.target.value)!.color })} className="ml-2 rounded border border-border bg-bg-tertiary p-2">{collections.map(collection => <optgroup key={collection} label={t(`collections.${collection}`)}>{FX_CATALOG.filter(item => item.collection === collection).map(item => <option key={item.id} value={item.id}>{t(`presets.${item.id}`, { defaultValue: item.id })}</option>)}</optgroup>)}</select></label>
          <label>{t('color')}<input type="color" value={cue.color} onChange={e => update(cue.id, { color: e.target.value })} /></label>
          <label><input type="checkbox" checked={cue.sound} onChange={e => update(cue.id, { sound: e.target.checked })} /> {t('sound')}</label>
        </div>
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          {(['start', 'end', 'x', 'y', 'size', 'rotation', 'intensity', 'volume', 'seed'] as const).map(key => <label key={key} className="text-xs">{t(key)}<input type="number" value={cue[key] ?? 0} min={key === 'rotation' ? -180 : key === 'end' ? cue.start + .1 : 0} max={key === 'start' || key === 'end' ? duration : undefined} step={key === 'seed' ? 1 : .1} onChange={e => { const value = e.target.valueAsNumber; if (Number.isFinite(value) && (key !== 'start' || value < cue.end) && (key !== 'end' || value > cue.start)) update(cue.id, { [key]: value }) }} className="mt-1 min-h-9 w-full rounded border border-border bg-bg-tertiary px-2" /></label>)}
        </div>
        <button type="button" onClick={() => onChange(cues.filter(item => item.id !== cue.id))} className="min-h-9 text-xs text-red-300">{t('remove')}</button>
      </div>)}
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={cues.length >= 64} onClick={() => onChange([...cues, ...parseSceneFx([{ id: `fx-${Date.now()}-${crypto.getRandomValues(new Uint32Array(1))[0]}`, kind: 'sparks', start: 0, end: Math.min(3, duration) }])])} className="min-h-10 rounded border border-border px-3 text-xs">{t('add')}</button>
        <button type="button" onClick={() => onShowcase('all')} className="min-h-10 rounded border border-cyan-400/40 px-3 text-xs">{t('showcase')}</button>
        <button type="button" onClick={() => onShowcase('anime')} className="min-h-10 rounded border border-violet-400/40 px-3 text-xs">{t('animeShowcase')}</button>
        <button type="button" onClick={() => onShowcase('retro')} className="min-h-10 rounded border border-amber-400/40 px-3 text-xs">{t('retroShowcase')}</button>
      </div>
    </fieldset>
  </details>
}
