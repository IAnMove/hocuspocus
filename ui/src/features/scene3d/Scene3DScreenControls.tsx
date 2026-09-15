import type { ApiOutput } from '../../api/client'
import { AssetInput } from '../asset-picker/AssetInput'
import { useUiTranslation } from '../../i18n'
import { defaultMediaScreen, defaultModelScreen, pickScreenAnchor, type MediaScreen } from './mediaScreen'
import { pickerOutputFromSlot } from './slotSource'
import type { Scene3DSlot } from './types'

export function Scene3DScreenControls({ slot, meshes, nodes = meshes, items, disabled, onChange, onChoose, onRemove }: {
  slot: Scene3DSlot; meshes: string[]; nodes?: string[]; items: ApiOutput[]; disabled: boolean
  onChange: (screen: MediaScreen | undefined) => void; onChoose: (item: ApiOutput | null) => void; onRemove: () => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  if (slot.media === 'image' && (slot.surface !== 'cutout' || slot.slot !== 'background')) return null
  const screen = slot.screen
  const patch = (value: Partial<MediaScreen>) => onChange({ ...(slot.media === 'model3d' ? defaultModelScreen(nodes, meshes) : defaultMediaScreen()), ...screen, ...value })
  const field = (key: 'width' | 'height' | 'start' | 'speed', min: number, max: number) => <label className="flex items-center justify-between gap-2 text-xs">{t(`screens.${key}`)}
    <input type="number" aria-label={t(`screens.${key}`)} min={min} max={max} step="0.01" disabled={disabled} value={screen?.[key] ?? defaultMediaScreen()[key]}
      onChange={event => { const value = Number(event.target.value); if (event.target.value && Number.isFinite(value)) patch({ [key]: Math.max(min, Math.min(max, value)) }) }} className="min-h-9 w-20 rounded border border-border bg-bg-primary p-1" /></label>
  const offset = screen?.offset ?? [0, 0, 0]
  return <section className="mt-3 space-y-3 rounded-lg border border-border p-3" data-testid="scene3d-screen-controls">
    {slot.media === 'image' && <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" disabled={disabled} checked={Boolean(screen)} onChange={event => onChange(event.target.checked ? { ...defaultMediaScreen(), media: 'video', fit: 'cover' } : undefined)} />{t('screens.animateImage')}</label>}
    {slot.media === 'model3d' ? <label className="flex min-h-9 items-center gap-2"><input type="checkbox" disabled={disabled || !nodes.length} checked={Boolean(screen)} onChange={event => onChange(event.target.checked ? defaultModelScreen(nodes, meshes) : undefined)} />{t('screens.attach')}</label> : <strong>{t('screens.title')}</strong>}
    {screen && <>
      {slot.media === 'model3d' && <>
        <label className="block text-xs">{t('screens.mode')}<select aria-label={t('screens.mode')} disabled={disabled} value={screen.mode} onChange={event => {
          const mode = event.target.value === 'plane' ? 'plane' : 'mesh'
          const initial = defaultModelScreen(nodes, meshes)
          patch(mode === 'plane'
            ? { ...(!screen.anchor ? { pitch: initial.pitch, yaw: initial.yaw, roll: initial.roll } : {}),
                mode, targetMesh: 'HOCUS_SCREEN_PLANE', anchor: screen.anchor || pickScreenAnchor(nodes), width: screen.width >= 1 ? 0.32 : screen.width, height: screen.height >= 1 ? 0.22 : screen.height }
            : { mode, targetMesh: pickScreenAnchor(meshes) || meshes[0] || 'SCREEN_CONTENT' })
        }} className="mt-1 min-h-10 w-full rounded border border-border bg-bg-primary px-2">
          <option value="plane">{t('screens.modePlane')}</option>
          <option value="mesh">{t('screens.modeMesh')}</option>
        </select></label>
        {screen.mode === 'plane'
          ? <label className="block text-xs">{t('screens.anchor')}<select aria-label={t('screens.anchor')} disabled={disabled} value={screen.anchor} onChange={event => patch({ anchor: event.target.value })} className="mt-1 min-h-10 w-full rounded border border-border bg-bg-primary px-2">
              <option value="">{t('screens.chooseAnchor')}</option>
              {[...new Set([screen.anchor, ...nodes].filter(Boolean))].map(name => <option key={name} value={name}>{name}</option>)}
            </select></label>
          : <label className="block text-xs">{t('screens.mesh')}<select aria-label={t('screens.mesh')} disabled={disabled} value={screen.targetMesh} onChange={event => patch({ targetMesh: event.target.value })} className="mt-1 min-h-10 w-full rounded border border-border bg-bg-primary px-2">
              {[...new Set([screen.targetMesh, ...meshes])].map(name => <option key={name} value={name}>{name || t('screens.chooseMesh')}</option>)}
            </select></label>}
        {screen.mode === 'plane' && <div className="grid grid-cols-3 gap-2">
          {([
            ['screens.offsetX', 0],
            ['screens.offsetY', 1],
            ['screens.offsetZ', 2],
          ] as const).map(([key, index]) => <label key={key} className="block text-xs">{t(key)}
            <input type="number" aria-label={t(key)} min={-2} max={2} step="0.01" disabled={disabled} value={offset[index]}
              onChange={event => { const value = Number(event.target.value); if (!event.target.value || !Number.isFinite(value)) return; const next: [number, number, number] = [...offset]; next[index] = Math.max(-2, Math.min(2, value)); patch({ offset: next }) }}
              className="mt-1 min-h-9 w-full rounded border border-border bg-bg-primary p-1" /></label>)}
        </div>}
        {screen.mode === 'plane' && (['pitch', 'yaw', 'roll'] as const).map(key => <label key={key} className="flex items-center justify-between gap-2 text-xs">{t(`screens.${key}`)}
          <input type="number" aria-label={t(`screens.${key}`)} min={-180} max={180} step="1" disabled={disabled} value={Math.round(((screen[key] ?? 0) * 180) / Math.PI)}
            onChange={event => { const value = Number(event.target.value); if (event.target.value && Number.isFinite(value)) patch({ [key]: Math.max(-180, Math.min(180, value)) * Math.PI / 180 }) }}
            className="min-h-9 w-20 rounded border border-border bg-bg-primary p-1" /></label>)}
      </>}
      <AssetInput label={t('screens.content')} placeholder={t('screens.chooseContent')} items={items}
        value={pickerOutputFromSlot(screen.sourceUrl, screen.media, screen.sourceRef)} accept="image/*,video/*" optional disabled={disabled}
        constraints={{ kinds: ['image', 'video'], maxCount: 1, optional: true }} onChoose={onChoose} />
      <label className="flex items-center justify-between gap-2">{t('screens.fit')}<select aria-label={t('screens.fit')} value={screen.fit} disabled={disabled} onChange={event => patch({ fit: event.target.value as MediaScreen['fit'] })} className="min-h-9 rounded border border-border bg-bg-primary px-2">
        <option value="contain">{t('screens.contain')}</option><option value="cover">{t('screens.cover')}</option></select></label>
      {slot.media === 'screen' && <label className="flex items-center justify-between gap-2">{t('screens.style')}<select aria-label={t('screens.style')} disabled={disabled} value={screen.style} onChange={event => patch({ style: event.target.value as MediaScreen['style'] })} className="min-h-9 rounded border border-border bg-bg-primary px-2">
        {(['monitor', 'billboard', 'frameless'] as const).map(style => <option key={style} value={style}>{t(`screens.${style}`)}</option>)}</select></label>}
      {slot.media !== 'image' && <div className="grid grid-cols-2 gap-3">{field('width', .02, 80)}{field('height', .02, 80)}</div>}
      <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={screen.flipY} disabled={disabled} onChange={event => patch({ flipY: event.target.checked })} />{t('screens.flipY')}</label>
      {screen.media === 'video' && <><div className="grid grid-cols-2 gap-3">{field('start', 0, 86400)}{field('speed', .05, 8)}</div>
        <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={screen.loop} disabled={disabled} onChange={event => patch({ loop: event.target.checked })} />{t('screens.loop')}</label><p className="text-xs text-text-muted">{t('screens.clockHelp')}</p></>}
    </>}
    {slot.media === 'screen' && <button type="button" disabled={disabled} onClick={onRemove} className="min-h-9 rounded border border-border px-3">{t('screens.remove')}</button>}
  </section>
}
