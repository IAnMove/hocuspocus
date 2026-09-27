import { useUiTranslation } from '../../i18n'
import type { Scene3DDocument, Scene3DSlot } from './types'

const inputClass = 'min-h-9 w-20 rounded border border-border bg-bg-tertiary px-2'
type FloorStyle = NonNullable<NonNullable<Scene3DDocument['environment']>['floorStyle']>

function withFloorStyle(environment: NonNullable<Scene3DDocument['environment']>, value: string) {
  const floorStyle = value as FloorStyle
  const reflectiveFloor = floorStyle === 'backdrop' || floorStyle === 'road' ? false : floorStyle === 'mirror' || environment.reflectiveFloor
  return { ...environment, floorStyle, reflectiveFloor }
}

export function CinematicControls({ environment, disabled, onChange }: {
  environment: Scene3DDocument['environment']; disabled: boolean; onChange: (value: Scene3DDocument['environment']) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  return <fieldset disabled={disabled} className="rounded-lg border border-border p-3 text-xs">
    <label className="flex min-h-9 items-center gap-2 font-semibold"><input type="checkbox" checked={Boolean(environment)} onChange={e => onChange(e.target.checked ? { reflectiveFloor: true, platform: false, bloom: .48 } : undefined)} />{t('cinematic.title')}</label>
    {environment && <div className="flex flex-wrap items-center gap-4">
      <label><input type="checkbox" aria-label={t('cinematic.floor')} checked={environment.reflectiveFloor} onChange={e => onChange({ ...environment, reflectiveFloor: e.target.checked })} /> {t('cinematic.floor')}</label>
      <label>{t('cinematic.floorStyle')} <select aria-label={t('cinematic.floorStyle')} className="min-h-9 rounded border border-border bg-bg-tertiary px-2" value={environment.floorStyle ?? 'tiles'} onChange={e => onChange(withFloorStyle(environment, e.target.value))}>
        <option value="road">{t('cinematic.road')}</option><option value="backdrop">{t('cinematic.backdropFloor')}</option><option value="tiles">{t('cinematic.tiles')}</option><option value="mirror">{t('cinematic.mirror')}</option><option value="none">{t('cinematic.noFloor')}</option>
      </select></label>
      {environment.floorStyle === 'road' && <EndlessRoadControls environment={environment} onChange={onChange} />}
      {environment.floorStyle === 'backdrop' && <label>{t('cinematic.floorSourceHeight')} <input type="range" min="0.1" max="1" step="0.05" value={environment.floorSourceHeight ?? 1} onChange={e => onChange({ ...environment, floorSourceHeight: e.target.valueAsNumber })} /></label>}
      <label>{t('cinematic.floorColor')} <input type="color" value={environment.floorColor ?? '#1c222c'} onChange={e => onChange({ ...environment, floorColor: e.target.value })} /></label>
      <label><input type="checkbox" checked={environment.platform} onChange={e => onChange({ ...environment, platform: e.target.checked })} /> {t('cinematic.platform')}</label>
      <label>{t('cinematic.bloom')} <input className={inputClass} type="number" min="0" max="1.5" step=".05" value={environment.bloom} onChange={e => { if (Number.isFinite(e.target.valueAsNumber)) onChange({ ...environment, bloom: Math.max(0, Math.min(1.5, e.target.valueAsNumber)) }) }} /></label>
    </div>}
    <p className="mt-2 text-text-muted">{t('cinematic.help')}</p>
  </fieldset>
}

export function AppearanceControls({ slot, disabled, onChange }: {
  slot: Scene3DSlot; disabled: boolean; onChange: (patch: Partial<Scene3DSlot>) => void
}) {
  const { t } = useUiTranslation('scene3dEditor'), appearance = slot.appearance
  if (slot.media !== 'model3d') return null
  return <fieldset disabled={disabled} className="my-2 rounded-lg border border-border p-2 text-xs">
    <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={Boolean(appearance)} onChange={e => onChange({ appearance: e.target.checked ? { start: 2, duration: .8, color: '#83e8ff' } : undefined })} />{t('cinematic.appearance')}</label>
    {appearance && <div className="flex flex-wrap items-center gap-3">
      {(['start', 'duration'] as const).map(key => <label key={key}>{t(`cinematic.${key}`)} <input className={inputClass} type="number" step=".1" min={key === 'start' ? 0 : .1} max={key === 'start' ? 600 : 30} value={appearance[key]} onChange={e => { if (Number.isFinite(e.target.valueAsNumber)) onChange({ appearance: { ...appearance, [key]: Math.max(key === 'start' ? 0 : .1, Math.min(key === 'start' ? 600 : 30, e.target.valueAsNumber)) } }) }} /></label>)}
      <label>{t('cinematic.color')} <input type="color" value={appearance.color} onChange={e => onChange({ appearance: { ...appearance, color: e.target.value } })} /></label>
    </div>}
    <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={slot.performance === 'idle'} onChange={e => onChange({ performance: e.target.checked ? 'idle' : undefined })} />{t('cinematic.idle')}</label>
    <p className="text-text-muted">{t('cinematic.idleHelp')}</p>
  </fieldset>
}

function EndlessRoadControls({ environment, onChange }: {
  environment: NonNullable<Scene3DDocument['environment']>; onChange: (value: Scene3DDocument['environment']) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const road = environment.road ?? { speed: 3, slope: 0, offset: 0 }
  return <>{(['speed', 'slope', 'offset'] as const).map(key => {
    const limit = { speed: 30, slope: 35, offset: 36000 }[key]
    return <label key={key}>{t(`cinematic.road_${key}`)} <input className={inputClass} type="number" min={-limit} max={limit} step="0.1" value={road[key]} onChange={e => {
      if (Number.isFinite(e.target.valueAsNumber)) onChange({ ...environment, road: { ...road, [key]: Math.max(-limit, Math.min(limit, e.target.valueAsNumber)) } })
    }} /></label>
  })}</>
}
