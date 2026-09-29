import type { Scene3DDocument } from './types.ts'
import type { AtmosSettings, ClearingPalette, TimeOfDay } from './atmos/params.ts'

const DAYS: TimeOfDay[] = ['dawn', 'morning', 'golden']
const PALETTES: ClearingPalette[] = ['green', 'autumn', 'blue']

type Props = {
  document: Scene3DDocument
  disabled: boolean
  label: (key: string) => string
  onChange: (atmos: AtmosSettings) => void
}

export function AtmosClearingControls({ document, disabled, label, onChange }: Props) {
  if (document.dressing !== 'atmos-clearing' || !document.atmos) return null
  const atmos = document.atmos
  const set = (patch: Partial<AtmosSettings>) => onChange({ ...atmos, ...patch })
  return (
    <div className="flex flex-wrap items-center gap-3 text-xs">
      <label className="flex items-center gap-2">{label('atmos.time')}
        <select disabled={disabled} value={atmos.timeOfDay} onChange={event => set({ timeOfDay: event.target.value as TimeOfDay })} className="min-h-10 rounded border border-border bg-bg-tertiary px-2">
          {DAYS.map(day => <option key={day} value={day}>{label(`atmos.day.${day}`)}</option>)}
        </select>
      </label>
      <label className="flex items-center gap-2">{label('atmos.palette')}
        <select disabled={disabled} value={atmos.palette} onChange={event => set({ palette: event.target.value as ClearingPalette })} className="min-h-10 rounded border border-border bg-bg-tertiary px-2">
          {PALETTES.map(palette => <option key={palette} value={palette}>{label(`atmos.swatch.${palette}`)}</option>)}
        </select>
      </label>
      {(['fogDensity', 'wind', 'motes'] as const).map(key => (
        <label key={key} className="flex items-center gap-2">{label(`atmos.${key}`)}
          <input disabled={disabled} type="range" min={0} max={1} step={0.01} value={atmos[key]} onChange={event => set({ [key]: Number(event.target.value) })} />
        </label>
      ))}
    </div>
  )
}
