import { useUiTranslation } from '../../i18n'
import type { Scene3DFraming, Scene3DSlot } from './types'

export function Scene3DFramingControls({ framing, slots, disabled, onChange }: {
  framing?: Scene3DFraming; slots: Scene3DSlot[]; disabled?: boolean; onChange: (value?: Scene3DFraming) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const subjects = slots.filter(slot => slot.media === 'model3d' || slot.surface === 'cutout')
  return <details className="rounded-lg border border-border p-3">
    <summary className="cursor-pointer text-sm font-semibold">{t('framing.title')}</summary>
    <fieldset disabled={disabled} className="mt-2 space-y-3 text-xs disabled:opacity-50">
      <label className="flex min-h-9 items-center gap-2"><input type="checkbox" disabled={!subjects.length} checked={Boolean(framing)} onChange={event => onChange(event.target.checked ? { targetSlot: subjects[0].id, anchor: 'head', from: [0, .1, 2], to: [0, .1, 1.5] } : undefined)} />{t('framing.title')}</label>
      {framing && <>
        <p className="text-text-muted">{t('framing.help')}</p>
        <div className="flex flex-wrap gap-3">
          <label className="flex min-w-0 flex-wrap items-center gap-1">{t('framing.target')}<select className="ml-2 max-w-full rounded border border-border bg-bg-tertiary p-2" value={framing.targetSlot} onChange={event => onChange({ ...framing, targetSlot: event.target.value })}>{subjects.map(slot => <option key={slot.id} value={slot.id}>{slot.sourceRef?.filename ?? slot.id}</option>)}</select></label>
          <label>{t('framing.anchor')}<select className="ml-2 rounded border border-border bg-bg-tertiary p-2" value={framing.anchor} onChange={event => onChange({ ...framing, anchor: event.target.value as Scene3DFraming['anchor'] })}>{(['head', 'center', 'feet'] as const).map(anchor => <option key={anchor} value={anchor}>{t(`framing.${anchor}`)}</option>)}</select></label>
        </div>
        {(['from', 'to', 'lookFrom', 'lookTo'] as const).map(key => <div key={key} className="flex flex-wrap items-center gap-2">
          <span>{t(`framing.${key}`)}</span>
          {(['X', 'Y', 'Z'] as const).map((axis, i) => <label key={axis}>{axis}<input aria-label={`${t(`framing.${key}`)} ${axis}`} type="number" step="0.05" value={(framing[key] ?? (key === 'lookTo' ? framing.lookFrom : undefined))?.[i] ?? 0} onChange={event => { if (!Number.isFinite(event.target.valueAsNumber)) return; const v = [...(framing[key] ?? (key === 'lookTo' ? framing.lookFrom : undefined) ?? [0, 0, 0])] as [number, number, number]; v[i] = event.target.valueAsNumber; onChange({ ...framing, [key]: v }) }} className="ml-1 min-h-9 w-20 rounded border border-border bg-bg-tertiary px-2" /></label>)}
        </div>)}
        <div className="flex flex-wrap gap-3">{(['orbitTurns', 'rollFrom', 'rollTo'] as const).map(key => <label key={key}>{t(`framing.${key === 'orbitTurns' ? 'orbit' : key}`)}<input type="number" step={key === 'orbitTurns' ? .025 : 1} value={framing[key] ?? (key === 'rollTo' ? framing.rollFrom : 0) ?? 0} onChange={event => { if (Number.isFinite(event.target.valueAsNumber)) onChange({ ...framing, [key]: event.target.valueAsNumber }) }} className="ml-2 min-h-9 w-20 rounded border border-border bg-bg-tertiary px-2" /></label>)}</div>
        <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={framing.relativeToFacing !== false} onChange={event => onChange({ ...framing, relativeToFacing: event.target.checked })} />{t('framing.facing')}</label>
      </>}
    </fieldset>
  </details>
}
