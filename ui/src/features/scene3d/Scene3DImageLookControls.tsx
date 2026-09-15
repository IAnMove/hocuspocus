import { useUiTranslation } from '../../i18n'
import type { ImageLook } from './imageLook'

export function Scene3DImageLookControls({ value = {}, disabled, onChange }: {
  value?: ImageLook; disabled: boolean; onChange: (value: ImageLook) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  return <fieldset disabled={disabled} className="my-2 flex flex-wrap items-center gap-3 rounded border border-border p-2 text-xs">
    <legend className="px-1">{t('imageLook.title')}</legend>
    <label className="flex min-h-9 items-center gap-2">{t('imageLook.roll')}<input className="w-20 rounded border border-border bg-bg-tertiary p-2" type="number" min="-180" max="180" step="1" value={value.roll ?? 0} onChange={e => { if (Number.isFinite(e.target.valueAsNumber)) onChange({ ...value, roll: Math.max(-180, Math.min(180, e.target.valueAsNumber)) }) }} /></label>
    <label className="flex min-h-9 items-center gap-2"><input type="color" value={value.tint ?? '#ffffff'} onChange={event => onChange({ ...value, tint: event.target.value })} />{t('imageLook.tint')}</label>
    <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={value.unlit === true} onChange={event => onChange({ ...value, unlit: event.target.checked })} />{t('imageLook.unlit')}</label>
    <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={value.grounded === true} onChange={event => onChange({ ...value, grounded: event.target.checked, shadow: value.shadow ?? .45 })} />{t('imageLook.grounded')}</label>
    {value.grounded && <label className="flex min-h-9 items-center gap-2">{t('imageLook.shadow')}<input type="range" min="0" max="1" step="0.05" value={value.shadow ?? 0} onChange={event => onChange({ ...value, shadow: event.target.valueAsNumber })} /></label>}
    <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={Boolean(value.psx)} onChange={event => onChange({ ...value, psx: event.target.checked ? 1.4 : undefined })} />{t('imageLook.psx')}</label>
    {Boolean(value.psx) && <label className="flex min-h-9 items-center gap-2">{t('imageLook.intensity')}<input type="range" min="0.5" max="2" step="0.1" value={value.psx} onChange={event => onChange({ ...value, psx: event.target.valueAsNumber })} /><output>{value.psx}</output></label>}
  </fieldset>
}
