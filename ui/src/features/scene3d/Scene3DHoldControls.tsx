import { useUiTranslation } from '../../i18n'
import { parseHold } from './handHold.ts'
import type { Scene3DSlot } from './types.ts'

const fieldClass = 'ml-2 min-h-10 w-20 rounded border border-border bg-bg-tertiary px-2'

export function Scene3DHoldControls({ slot, slots, disabled, onChange }: {
  slot: Scene3DSlot
  slots: readonly Scene3DSlot[]
  disabled: boolean
  onChange: (patch: Partial<Scene3DSlot>) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  if (!canHold(slot)) return null
  const carriers = slots.filter(item => item.id !== slot.id && item.media === 'model3d' && item.sourceUrl)
  const hold = parseHold(slot.hold, slot.id)
  if (!carriers.length && !hold) return null
  return <div className="mt-3 space-y-2">
    <label className="flex min-h-10 items-center gap-2 text-xs">
      <input type="checkbox" disabled={disabled || (!hold && !carriers.length)} checked={Boolean(hold)}
        onChange={event => onChange({ hold: event.target.checked ? { carrier: carriers[0]?.id ?? hold?.carrier ?? '', hand: 'right' } : undefined })} />
      {t('holdInHand')}
    </label>
    {hold && <div className="flex flex-wrap items-center gap-3">
      <label className="text-xs">{t('holdCarrier')}
        <select aria-label={`${t('holdCarrier')} ${slot.id}`} disabled={disabled} value={hold.carrier}
          className="ml-2 min-h-10 rounded border border-border bg-bg-tertiary px-2 text-xs"
          onChange={event => onChange({ hold: { ...hold, carrier: event.target.value } })}>
          {carriers.map(item => <option key={item.id} value={item.id}>{item.character?.name || item.id}</option>)}
          {!carriers.some(item => item.id === hold.carrier) && <option value={hold.carrier}>{hold.carrier}</option>}
        </select>
      </label>
      <label className="text-xs">{t('holdHand')}
        <select aria-label={`${t('holdHand')} ${slot.id}`} disabled={disabled} value={hold.hand}
          className="ml-2 min-h-10 rounded border border-border bg-bg-tertiary px-2 text-xs"
          onChange={event => onChange({ hold: { ...hold, hand: event.target.value === 'left' ? 'left' : 'right' } })}>
          <option value="right">{t('holdRight')}</option>
          <option value="left">{t('holdLeft')}</option>
        </select>
      </label>
      {([0, 1, 2] as const).map(axis => <label key={axis} className="text-xs">{t(axis === 0 ? 'holdOffsetX' : axis === 1 ? 'holdOffsetY' : 'holdOffsetZ')}
        <input aria-label={`${t(axis === 0 ? 'holdOffsetX' : axis === 1 ? 'holdOffsetY' : 'holdOffsetZ')} ${slot.id}`} type="number"
          min={-2} max={2} step={0.01} disabled={disabled} value={hold.offset?.[axis] ?? 0} className={fieldClass}
          onChange={event => {
            const offset = [...(hold.offset ?? [0, 0, 0])] as [number, number, number]
            const raw = event.target.valueAsNumber
            offset[axis] = Number.isFinite(raw) ? Math.min(2, Math.max(-2, raw)) : 0
            onChange({ hold: { ...hold, offset } })
          }} />
      </label>)}
      <p className="w-full text-xs text-text-muted">{t('holdHelp')}</p>
    </div>}
  </div>
}

function canHold(slot: Scene3DSlot) {
  if (slot.media !== 'model3d' && slot.media !== 'image') return false
  return !(slot.loop?.cylinder || slot.surface === 'floor' || slot.surface === 'wall' || slot.surface === 'environment')
}
