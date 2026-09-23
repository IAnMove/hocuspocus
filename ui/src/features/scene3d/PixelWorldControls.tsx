import { useUiTranslation } from '../../i18n'
import { defaultPixelWorld, type PixelWorld } from './pixel/pixelWorld'
import { PIXEL_PALETTE_IDS, PIXEL_PALETTES } from './pixel/pixelPalettes'
import { isPixelDressing, PIXEL_DRESSINGS } from './pixel/pixelWorldSet'
import type { Scene3DDocument } from './types'

type Patch = Pick<Scene3DDocument, 'pixelWorld' | 'dressing'>
const RANGES = { hold: [.5, 120, .5], meteors: [0, 1, .05], pixelSize: [1, 8, 1], levels: [4, 64, 1], dither: [0, 1, .05], screenGlow: [0, 2, .05] } as const

/** Lighting program, pixel look and screen light of a pixel world. */
export function PixelWorldControls({ pixelWorld, dressing, tvs, disabled, onChange, onAddTv }: {
  pixelWorld: PixelWorld | undefined; dressing: Scene3DDocument['dressing']; tvs: number; disabled: boolean
  onChange: (patch: Partial<Patch>) => void; onAddTv: () => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const set = (value: Partial<PixelWorld>) => pixelWorld && onChange({ pixelWorld: { ...pixelWorld, ...value } })
  return <fieldset disabled={disabled} className="rounded-lg border border-border p-3 text-xs" data-testid="pixel-world-controls">
    <label className="flex min-h-9 items-center gap-2 font-semibold"><input type="checkbox" checked={Boolean(pixelWorld)} onChange={e => onChange({ pixelWorld: e.target.checked ? defaultPixelWorld() : undefined })} />{t('pixelWorld.enable')}</label>
    {pixelWorld && <div className="mt-2 space-y-3">
      <label className="flex items-center gap-2">{t('pixelWorld.setting')}
        <select className="min-h-9 rounded border border-border bg-bg-tertiary px-2" value={isPixelDressing(dressing) ? dressing : ''} onChange={e => onChange({ dressing: (e.target.value || undefined) as Scene3DDocument['dressing'] })}>
          <option value="">{t('pixelWorld.noSet')}</option>
          {PIXEL_DRESSINGS.map(kind => <option key={kind} value={kind}>{t(`pixelWorld.set.${kind}`)}</option>)}
        </select></label>
      <div>
        <p className="mb-1 font-medium">{t('pixelWorld.palettes')}</p>
        <div className="flex flex-wrap items-center gap-1.5">
          {pixelWorld.palettes.map((id, index) => <button key={`${id}-${index}`} type="button" aria-label={t('pixelWorld.remove', { name: t(`pixelWorld.palette.${id}`) })} disabled={pixelWorld.palettes.length < 2}
            onClick={() => set({ palettes: pixelWorld.palettes.filter((_, at) => at !== index) })}
            className="flex min-h-9 items-center gap-1.5 rounded-full border border-border px-2.5 hover:bg-bg-hover disabled:opacity-100">
            <span aria-hidden className="h-3 w-6 rounded-sm" style={{ background: `linear-gradient(90deg, ${PIXEL_PALETTES[id].sky.join(',')})` }} />{t(`pixelWorld.palette.${id}`)}{pixelWorld.palettes.length > 1 && <span aria-hidden>×</span>}
          </button>)}
          {pixelWorld.palettes.length < 8 && <select aria-label={t('pixelWorld.add')} value="" onChange={e => { if (e.target.value) set({ palettes: [...pixelWorld.palettes, e.target.value as PixelWorld['palettes'][number]] }) }}
            className="min-h-9 rounded border border-dashed border-border bg-bg-tertiary px-2">
            <option value="">+ {t('pixelWorld.add')}</option>
            {PIXEL_PALETTE_IDS.map(id => <option key={id} value={id}>{t(`pixelWorld.palette.${id}`)}</option>)}
          </select>}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {(Object.keys(RANGES) as (keyof typeof RANGES)[]).map(key => {
          const [min, max, step] = RANGES[key]
          return <label key={key} className="flex items-center justify-between gap-2">{t(`pixelWorld.${key}`)}
            <span className="flex items-center gap-2"><input type="range" min={min} max={max} step={step} value={pixelWorld[key]} aria-label={t(`pixelWorld.${key}`)}
              onChange={e => set({ [key]: e.target.valueAsNumber })} className="w-28" /><output className="w-8 text-right tabular-nums">{pixelWorld[key]}</output></span></label>
        })}
      </div>
      <div className="flex items-center gap-3"><button type="button" onClick={onAddTv} className="min-h-9 rounded border border-border px-3 hover:bg-bg-hover">{t('pixelWorld.addTv')}</button>
        {tvs > 0 && <span className="text-text-muted">{t('pixelWorld.tvs', { count: tvs })}</span>}</div>
    </div>}
    <p className="mt-2 text-text-muted">{t('pixelWorld.help')}</p>
  </fieldset>
}
