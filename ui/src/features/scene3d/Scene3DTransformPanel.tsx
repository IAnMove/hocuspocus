import { Maximize2, Move3D, RotateCcw, Rotate3D } from 'lucide-react'
import { useUiTranslation } from '../../i18n'
import type { Scene3DSlot, Vec3 } from './types'
import type { TransformMode, TransformPatch } from './transformGizmo'

const modes = [{ id: 'translate', Icon: Move3D }, { id: 'rotate', Icon: Rotate3D }, { id: 'scale', Icon: Maximize2 }] as const

export function Scene3DTransformPanel({ slot, mode, disabled, onMode, onChange, onReset, showModes = true }: {
  slot: Scene3DSlot; mode: TransformMode; disabled: boolean
  onMode: (mode: TransformMode) => void; onChange: (patch: TransformPatch) => void; onReset: () => void
  showModes?: boolean
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const { t: sceneT } = useUiTranslation('scene3d')
  return <section className="space-y-3 rounded-xl border border-border bg-bg-secondary p-3" data-testid="scene3d-transforms">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h3 className="text-sm font-semibold text-text-primary">{sceneT(`stage.slot.${slot.slot}`)}</h3>
      {showModes && <div className="flex flex-wrap gap-2">
        {modes.map(({ id, Icon }) => <button key={id} type="button" disabled={disabled} onClick={() => onMode(id)} aria-pressed={mode === id}
          className={`inline-flex min-h-10 items-center gap-2 rounded-lg border px-3 text-xs font-semibold disabled:opacity-40 ${mode === id ? 'border-cyan-300 bg-cyan-300/15 text-cyan-100' : 'border-border text-text-secondary'}`}><Icon size={17} />{t(id)}</button>)}
      </div>}
    </div>
    <div className="grid gap-3 sm:grid-cols-2">
      <fieldset disabled={disabled}><legend className="mb-2 text-xs text-text-secondary">{t('position')}</legend>
        <div className="grid grid-cols-3 gap-2">{(['X', 'Y', 'Z'] as const).map((axis, index) => <label key={axis} className={`text-xs font-bold ${['text-red-300', 'text-green-300', 'text-blue-300'][index]}`}>{axis}
          <input type="number" step="0.05" value={Number(slot.position[index].toFixed(3))} aria-label={`${t('position')} ${axis}`} onChange={event => {
            if (!event.target.value.trim()) return
            const value = Number(event.target.value)
            if (Number.isFinite(value)) onChange({ position: slot.position.map((current, i) => i === index ? value : current) as unknown as Vec3 })
          }} className="mt-1 min-h-10 w-full rounded-lg border border-border bg-bg-primary px-2 font-normal text-text-primary disabled:opacity-40" />
        </label>)}</div>
      </fieldset>
      <div className="grid grid-cols-2 gap-2">
        <label className="text-xs text-text-secondary">{t('size')}<input type="number" min="0.05" max="100" step="0.05" disabled={disabled} value={Number(slot.scale.toFixed(3))}
          onChange={event => { const scale = Number(event.target.value); if (Number.isFinite(scale) && scale >= 0.05) onChange({ scale: Math.min(100, scale) }) }} className="mt-2 min-h-10 w-full rounded-lg border border-border bg-bg-primary px-2 text-text-primary disabled:opacity-40" /></label>
        <label className="text-xs text-text-secondary">{t('rotationX')}<input type="number" step="5" disabled={disabled} value={Number(((slot.rotationX ?? 0) * 180 / Math.PI).toFixed(1))}
          onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value)) onChange({ rotationX: value * Math.PI / 180 }) }} className="mt-2 min-h-10 w-full rounded-lg border border-border bg-bg-primary px-2 text-text-primary disabled:opacity-40" /></label>
        <label className="text-xs text-text-secondary">{t('yaw')}<input type="number" step="5" disabled={disabled} value={Number((slot.rotationY * 180 / Math.PI).toFixed(1))}
          onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value)) onChange({ rotationY: value * Math.PI / 180 }) }} className="mt-2 min-h-10 w-full rounded-lg border border-border bg-bg-primary px-2 text-text-primary disabled:opacity-40" /></label>
        <label className="text-xs text-text-secondary">{t('rotationZ')}<input type="number" step="5" disabled={disabled} value={Number(((slot.rotationZ ?? 0) * 180 / Math.PI).toFixed(1))}
          onChange={event => { const value = Number(event.target.value); if (Number.isFinite(value)) onChange({ rotationZ: value * Math.PI / 180 }) }} className="mt-2 min-h-10 w-full rounded-lg border border-border bg-bg-primary px-2 text-text-primary disabled:opacity-40" /></label>
      </div>
    </div>
    <div className="flex flex-wrap gap-2">
      <button type="button" disabled={disabled} onClick={() => onChange({ scale: Math.max(0.05, slot.scale / 1.25) })} className="min-h-10 rounded-lg border border-border px-3 text-xs text-text-primary disabled:opacity-40">− {t('smaller')}</button>
      <button type="button" disabled={disabled} onClick={() => onChange({ scale: Math.min(100, slot.scale * 1.25) })} className="min-h-10 rounded-lg border border-border px-3 text-xs text-text-primary disabled:opacity-40">+ {t('larger')}</button>
      <button type="button" disabled={disabled} onClick={onReset} className="ml-auto inline-flex min-h-10 items-center gap-2 rounded-lg border border-border px-3 text-xs text-text-secondary disabled:opacity-40"><RotateCcw size={14} />{t('reset')}</button>
    </div>
    <p className="text-xs leading-5 text-text-muted">{t('gizmoHelp')}</p>
  </section>
}
