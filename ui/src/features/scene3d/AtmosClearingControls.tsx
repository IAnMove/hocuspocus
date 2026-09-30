import type { Scene3DDocument } from './types.ts'
import type { AtmosSettings } from './atmos/params.ts'
import { atmosSet } from './atmos/registry.ts'

type Props = {
  document: Scene3DDocument
  disabled: boolean
  label: (key: string) => string
  onChange: (atmos: AtmosSettings) => void
}

export function AtmosClearingControls({ document, disabled, label, onChange }: Props) {
  const set = atmosSet(document.dressing)
  if (!set || !document.atmos) return null
  const atmos = document.atmos
  const patch = (next: Partial<AtmosSettings>) => onChange({ ...atmos, ...next })
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs">
      <label className="flex items-center gap-2">{label('atmos.time')}
        <select disabled={disabled} value={atmos.timeOfDay} onChange={event => patch({ timeOfDay: event.target.value })} className="min-h-10 rounded border border-border bg-bg-tertiary px-2">
          {Object.keys(set.times).map(day => <option key={day} value={day}>{label(`atmos.day.${day}`)}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-2">{label('atmos.palette')}
        <select disabled={disabled} value={atmos.palette} onChange={event => patch({ palette: event.target.value })} className="min-h-10 rounded border border-border bg-bg-tertiary px-2">
          {Object.keys(set.palettes).map(palette => <option key={palette} value={palette}>{label(`atmos.swatch.${palette}`)}</option>)}
        </select>
      </label>
      {(['fogDensity', 'wind', 'motes'] as const).map(key => (
        <label key={key} className="flex items-center gap-2">{label(`atmos.${key}`)}
          <input disabled={disabled} type="range" min={0} max={1} step={0.01} value={atmos[key]} onChange={event => patch({ [key]: Number(event.target.value) })} />
        </label>
      ))}
      {set.variant ? (
        <label className="flex items-center gap-2">{label(set.variant.labelKey)}
          <input disabled={disabled} type="range" min={set.variant.min} max={set.variant.max} step={1} value={atmos.variant ?? set.variant.min} onChange={event => patch({ variant: Number(event.target.value) })} />
        </label>
      ) : null}
    </div>
  )
}
