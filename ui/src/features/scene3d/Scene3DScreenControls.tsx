import type { ReactNode } from 'react'
import type { ApiOutput } from '../../api/client'
import { AssetInput } from '../asset-picker/AssetInput'
import { useUiTranslation } from '../../i18n'
import { defaultMediaScreen, defaultModelScreen, pickScreenAnchor, type MediaScreen } from './mediaScreen'
import { pickerOutputFromSlot } from './slotSource'
import type { Scene3DSlot } from './types'
import { Scene3DPoseSequenceControls } from './Scene3DPoseSequenceControls'

export function Scene3DScreenControls({ slot, meshes, nodes = meshes, items, disabled, workspace, onChange, onChoose, onRemove }: {
  slot: Scene3DSlot; meshes: string[]; nodes?: string[]; items: ApiOutput[]; disabled: boolean; workspace?: string
  onChange: (screen: MediaScreen | undefined) => void; onChoose: (item: ApiOutput | null) => void; onRemove: () => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  if (!supportsScreenControls(slot)) return null
  const screen = slot.screen
  const patch = (value: Partial<MediaScreen>) => onChange({ ...(slot.media === 'model3d' ? defaultModelScreen(nodes, meshes) : defaultMediaScreen()), ...screen, ...value })
  const field = (key: 'width' | 'height' | 'start' | 'speed', min: number, max: number) => <label className="flex items-center justify-between gap-2 text-xs">{t(`screens.${key}`)}
    <input type="number" aria-label={t(`screens.${key}`)} min={min} max={max} step="0.01" disabled={disabled} value={screen?.[key] ?? defaultMediaScreen()[key]}
      onChange={event => { const value = Number(event.target.value); if (event.target.value && Number.isFinite(value)) patch({ [key]: Math.max(min, Math.min(max, value)) }) }} className="min-h-9 w-20 rounded border border-border bg-bg-primary p-1" /></label>
  return <section className="mt-3 space-y-3 rounded-lg border border-border p-3" data-testid="scene3d-screen-controls">
    {slot.media === 'image' && <label className="flex min-h-10 items-center gap-2 text-sm"><input type="checkbox" disabled={disabled} checked={Boolean(screen)} onChange={event => onChange(event.target.checked ? { ...defaultMediaScreen(), media: 'video', fit: 'cover' } : undefined)} />{t('screens.animateImage')}</label>}
    {slot.media === 'model3d' ? <label className="flex min-h-9 items-center gap-2"><input type="checkbox" disabled={disabled || !nodes.length} checked={Boolean(screen)} onChange={event => onChange(event.target.checked ? defaultModelScreen(nodes, meshes) : undefined)} />{t('screens.attach')}</label> : slot.media === 'screen' ? <strong>{t('screens.title')}</strong> : null}
    {screen && <>
      {slot.media === 'model3d' && <ModelScreenPlacement screen={screen} nodes={nodes} meshes={meshes} disabled={disabled} patch={patch} />}
      {!screen.poseSequence && <ScreenSourceControls screen={screen} items={items} disabled={disabled} onChoose={onChoose} patch={patch} />}
      {slot.media === 'image' && <Scene3DPoseSequenceControls key={`${slot.id}:${slot.sourceUrl}`} screen={screen} baseUrl={slot.sourceUrl} items={items} disabled={disabled} workspace={workspace} onChange={onChange} />}
      {slot.media === 'screen' && <label className="flex items-center justify-between gap-2">{t('screens.style')}<select aria-label={t('screens.style')} disabled={disabled} value={screen.style} onChange={event => patch({ style: event.target.value as MediaScreen['style'] })} className="min-h-9 rounded border border-border bg-bg-primary px-2">
        {(['monitor', 'billboard', 'frameless'] as const).map(style => <option key={style} value={style}>{t(`screens.${style}`)}</option>)}</select></label>}
      {slot.media !== 'image' && <div className="grid grid-cols-2 gap-3">{field('width', .02, 80)}{field('height', .02, 80)}</div>}
      <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={screen.flipY} disabled={disabled} onChange={event => patch({ flipY: event.target.checked })} />{t('screens.flipY')}</label>
      <ScreenPlaybackControls screen={screen} disabled={disabled} patch={patch} field={field} />
    </>}
    {slot.media === 'screen' && <button type="button" disabled={disabled} onClick={onRemove} className="min-h-9 rounded border border-border px-3">{t('screens.remove')}</button>}
  </section>
}

function ScreenSourceControls({ screen, items, disabled, onChoose, patch }: {
  screen: MediaScreen; items: ApiOutput[]; disabled: boolean
  onChoose: (item: ApiOutput | null) => void; patch: (value: Partial<MediaScreen>) => void
}) {
  const { t } = useUiTranslation('scene3dEditor')
  return <>
    <AssetInput label={t('screens.content')} placeholder={t('screens.chooseContent')} items={items}
      value={pickerOutputFromSlot(screen.sourceUrl, screen.media, screen.sourceRef)} accept="image/*,video/*" optional disabled={disabled}
      constraints={{ kinds: ['image', 'video'], maxCount: 1, optional: true }} onChoose={onChoose} />
    <label className="flex min-h-9 items-center gap-2"><input type="checkbox" disabled={disabled} checked={Boolean(screen.transparent)} onChange={event => patch({ transparent: event.target.checked })} />{t('screens.transparent')}</label>
    {screen.transparent && <p className="text-xs text-text-muted">{t('screens.transparentHelp')}</p>}
    <label className="flex items-center justify-between gap-2">{t('screens.fit')}<select aria-label={t('screens.fit')} value={screen.fit} disabled={disabled} onChange={event => patch({ fit: event.target.value as MediaScreen['fit'] })} className="min-h-9 rounded border border-border bg-bg-primary px-2">
      <option value="contain">{t('screens.contain')}</option><option value="cover">{t('screens.cover')}</option></select></label>
  </>
}

function ScreenPlaybackControls({ screen, disabled, patch, field }: {
  screen: MediaScreen; disabled: boolean; patch: (value: Partial<MediaScreen>) => void
  field: (key: 'start' | 'speed', min: number, max: number) => ReactNode
}) {
  const { t } = useUiTranslation('scene3dEditor')
  if (screen.media !== 'video' && !screen.poseSequence) return null
  return <><div className="grid grid-cols-2 gap-3">{field('start', 0, 86400)}{field('speed', .05, 8)}</div>
    <label className="flex min-h-9 items-center gap-2"><input type="checkbox" checked={screen.loop} disabled={disabled} onChange={event => patch({ loop: event.target.checked })} />{t('screens.loop')}</label>{screen.media === 'video' && <p className="text-xs text-text-muted">{t('screens.clockHelp')}</p>}</>
}

function supportsScreenControls(slot: Scene3DSlot) {
  return slot.media !== 'image' || slot.surface === 'cutout'
}

function ModelScreenPlacement({ screen, nodes, meshes, disabled, patch }: {
  screen: MediaScreen; nodes: string[]; meshes: string[]; disabled: boolean; patch: (value: Partial<MediaScreen>) => void
}) {
  const { t } = useUiTranslation('scene3dEditor'), offset = screen.offset ?? [0, 0, 0]
  return <>
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
  </>
}
