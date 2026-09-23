import { useState } from 'react'
import { useUiTranslation } from '../../i18n'
import type { PixelWorld } from './pixel/pixelWorld'
import { PALETTE_COLOR_KEYS, paletteColor, paletteWith, type PixelPaletteId } from './pixel/pixelPalettes'
import { resolvePixelScene, type PixelScene, type PixelWorldKind } from './pixel/pixelScene'

type Slider = keyof Pick<PixelScene, 'bodyX' | 'bodyY' | 'bodySize' | 'crescent' | 'mountains' | 'roughness' | 'snow' | 'hills' | 'trees' | 'stars' | 'auroraHeight' | 'ripple' | 'city' | 'windows'>

/** Sliders that matter for a world: no waves in the desert, no windows
 *  outside the city, no phase on the sun. */
function slidersFor(kind: PixelWorldKind, scene: PixelScene): Slider[] {
  const body: Slider[] = scene.body === 'none' ? [] : ['bodyX', 'bodyY', 'bodySize', ...(scene.body === 'sun' ? [] : ['crescent' as const])]
  const land: Slider[] = ['mountains', 'roughness', 'snow', 'hills', 'trees']
  return [...body, ...land, 'stars', 'auroraHeight', ...(kind === 'pixel-desert' ? [] : ['ripple' as const]), ...(kind === 'pixel-city' ? ['city' as const, 'windows' as const] : [])]
}

export function PixelWorldSceneControls({ kind, pixelWorld, onChange }: {
  kind: PixelWorldKind; pixelWorld: PixelWorld; onChange: (value: PixelWorld) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  const scene = resolvePixelScene(kind, pixelWorld.scene)
  const patch = (value: Partial<PixelScene>) => onChange({ ...pixelWorld, scene: { ...pixelWorld.scene, ...value } })
  return <details open className="rounded-lg border border-border/70 p-2" data-testid="pixel-scene-controls">
    <summary className="cursor-pointer font-medium">{t('pixelWorld.scene.title')}</summary>
    <div className="mt-2 space-y-2">
      <div className="flex flex-wrap gap-2">
        <button type="button" title={t('pixelWorld.scene.reimagineHelp')} onClick={() => patch({ seed: 1 + Math.floor(Math.random() * 999998) })}
          className="min-h-9 rounded border border-cyan-300/50 px-3 text-cyan-100 hover:bg-cyan-300/10">{t('pixelWorld.scene.reimagine')}</button>
        <button type="button" onClick={() => onChange({ ...pixelWorld, scene: undefined })} className="min-h-9 rounded border border-border px-3 hover:bg-bg-hover">{t('pixelWorld.scene.reset')}</button>
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <label className="flex items-center justify-between gap-2">{t('pixelWorld.scene.body')}
          <select value={scene.body} onChange={e => patch({ body: e.target.value as PixelScene['body'] })} className="min-h-9 rounded border border-border bg-bg-tertiary px-2">
            {(['moon', 'sun', 'planet', 'none'] as const).map(body => <option key={body} value={body}>{t(`pixelWorld.scene.bodyKind.${body}`)}</option>)}
          </select></label>
        <label className="flex items-center justify-between gap-2">{t('pixelWorld.scene.meteorDirection')}
          <select value={scene.meteorDirection} onChange={e => patch({ meteorDirection: e.target.value as PixelScene['meteorDirection'] })} className="min-h-9 rounded border border-border bg-bg-tertiary px-2">
            {(['both', 'left', 'right'] as const).map(way => <option key={way} value={way}>{t(`pixelWorld.scene.meteor.${way}`)}</option>)}
          </select></label>
        {slidersFor(kind, scene).map(key => <label key={key} className="flex items-center justify-between gap-2">{t(`pixelWorld.scene.${key}`)}
          <input type="range" aria-label={t(`pixelWorld.scene.${key}`)} min={key === 'bodySize' ? .4 : 0} max={key === 'bodySize' ? 2.5 : 1} step={.01}
            value={scene[key]} onChange={e => patch({ [key]: e.target.valueAsNumber })} className="w-32" /></label>)}
        <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={scene.reeds} onChange={e => patch({ reeds: e.target.checked })} />{t('pixelWorld.scene.reeds')}</label>
      </div>
      <p className="text-text-muted">{t('pixelWorld.scene.lightHelp')}</p>
    </div>
  </details>
}

export function PixelWorldColorControls({ pixelWorld, onChange }: { pixelWorld: PixelWorld; onChange: (value: PixelWorld) => void }) {
  const { t } = useUiTranslation('scene3dEditor')
  const moods = [...new Set(pixelWorld.palettes)]
  const [chosen, setChosen] = useState<PixelPaletteId>(moods[0])
  const mood = moods.includes(chosen) ? chosen : moods[0]
  const colors = pixelWorld.colors?.[mood]
  const palette = paletteWith(mood, colors)
  const setColor = (key: typeof PALETTE_COLOR_KEYS[number], value: string) =>
    onChange({ ...pixelWorld, colors: { ...pixelWorld.colors, [mood]: { ...colors, [key]: value } } })
  const reset = () => {
    const rest = { ...pixelWorld.colors }
    delete rest[mood]
    onChange({ ...pixelWorld, colors: Object.keys(rest).length ? rest : undefined })
  }
  return <details className="rounded-lg border border-border/70 p-2" data-testid="pixel-color-controls">
    <summary className="cursor-pointer font-medium">{t('pixelWorld.colors.title')}</summary>
    <div className="mt-2 space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2">{t('pixelWorld.colors.mood')}
          <select value={mood} onChange={e => setChosen(e.target.value as PixelPaletteId)} className="min-h-9 rounded border border-border bg-bg-tertiary px-2">
            {moods.map(id => <option key={id} value={id}>{t(`pixelWorld.palette.${id}`)}</option>)}
          </select></label>
        {colors && <button type="button" onClick={reset} className="min-h-9 rounded border border-border px-3 hover:bg-bg-hover">{t('pixelWorld.colors.reset')}</button>}
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {PALETTE_COLOR_KEYS.map(key => <label key={key} className="flex min-h-9 items-center gap-2">
          <input type="color" aria-label={t(`pixelWorld.colors.${key}`)} value={paletteColor(palette, key)} onChange={e => setColor(key, e.target.value)} className="h-8 w-10 shrink-0 rounded border border-border bg-transparent" />
          <span className="truncate">{t(`pixelWorld.colors.${key}`)}</span></label>)}
      </div>
    </div>
  </details>
}
