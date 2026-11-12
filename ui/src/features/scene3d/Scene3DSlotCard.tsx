import type { TFunction } from 'i18next'
import { controlReason } from '../../i18n/controlLabel'
import type { ApiOutput } from '../../api/client'
import { AssetInput } from '../asset-picker/AssetInput.tsx'
import { AppearanceControls } from './CinematicControls'
import { Scene3DAnimationControls } from './Scene3DAnimationControls'
import { FaceDecalControls } from './FaceDecalControls'
import { Scene3DHoldControls } from './Scene3DHoldControls'
import { Scene3DImageLookControls } from './Scene3DImageLookControls'
import { Scene3DScreenControls } from './Scene3DScreenControls'
import { Scene3DWindowControls } from './Scene3DWindowControls'
import { applyScreenToAllTvs } from './pixel/pixelEdits'
import { commitSlotSourceChoice, pickerOutputFromSlot, type SlotSourceCapture, type SlotSourceLive } from './slotSource'
import { patchScene3DSlot } from './templates.ts'
import type { Scene3DClipCatalogEntry, Scene3DDocument, Scene3DLoop, Scene3DSlot } from './types.ts'

function SlotImageSurfaceControls({
  slot, exporting, editorT, onApplyScene,
}: {
  slot: Scene3DSlot
  exporting: boolean
  editorT: TFunction<'scene3dEditor'>
  onApplyScene: (updater: Scene3DDocument | ((current: Scene3DDocument) => Scene3DDocument), group?: string) => void
}) {
  if (slot.media !== 'image') return null
  return (
    <>
      <label className="my-2 flex min-h-9 items-center gap-2 text-xs"><span>{editorT('travel.surface')}</span><select aria-label={editorT('travel.surface')} disabled={exporting} value={slot.surface ?? 'backdrop'} onChange={event => onApplyScene(current => patchScene3DSlot(current, slot.id, { surface: event.target.value === 'backdrop' ? undefined : event.target.value as Scene3DSlot['surface'], loop: undefined }))} className="rounded border border-border bg-bg-tertiary p-2"><option value="backdrop">{editorT('travel.backdrop')}</option><option value="cutout">{editorT('travel.cutout')}</option><option value="environment">{editorT('cinematic.background')}</option><option value="wall">{editorT('travel.wall')}</option><option value="floor">{editorT('travel.floor')}</option></select></label>
      {slot.surface === 'cutout' && <Scene3DImageLookControls value={slot.imageLook} disabled={exporting} onChange={imageLook => onApplyScene(current => patchScene3DSlot(current, slot.id, { imageLook }))} />}
      {slot.surface === 'cutout' && slot.sourceUrl && <Scene3DWindowControls key={`${slot.id}:${slot.sourceUrl}`} sourceUrl={slot.sourceUrl} windows={slot.imageLook?.windows} disabled={exporting} onChange={windows => onApplyScene(current => patchScene3DSlot(current, slot.id, { imageLook: { ...slot.imageLook, windows } }))} />}
      {(slot.surface === 'floor' || slot.surface === 'wall') && numberField(editorT('travel.repeat'), slot.textureRepeat ?? (slot.surface === 'floor' ? 4 : 2), value => onApplyScene(current => patchScene3DSlot(current, slot.id, { textureRepeat: Math.max(1, Math.min(16, value)) })), 1, exporting)}
    </>
  )
}

function numberField(label: string, value: number, onChange: (value: number) => void, step = 0.05, disabled = false) {
  return (
    <label className="flex items-center gap-1 text-sm text-text-muted">
      {label}
      <input aria-label={label}
        type="number"
        step={step}
        disabled={disabled}
        value={Number.isFinite(value) ? value : 0}
        onChange={event => {
          const next = Number(event.target.value)
          if (Number.isFinite(next)) onChange(next)
        }}
        className="w-16 rounded border border-border bg-bg-tertiary px-1 py-0.5 text-sm text-text-primary disabled:opacity-40"
      />
    </label>
  )
}

export function Scene3DSlotCard({
  slot, selected, catalogs, slots, duration, templateId, workspace,
  exporting, editingLocked, imageItems, modelItems, videoItems, meshes, nodes, t, editorT,
  onSelect, onSpeech, onAssign, onApplyScene, onBumpGeneration, liveSource,
}: {
  slot: Scene3DSlot
  selected: boolean
  catalogs: Record<string, Scene3DClipCatalogEntry[]>
  slots: readonly Scene3DSlot[]
  duration: number
  templateId: string
  workspace: string
  exporting: boolean
  editingLocked: boolean
  imageItems: ApiOutput[]
  modelItems: ApiOutput[]
  videoItems: ApiOutput[]
  meshes: string[]
  nodes: string[]
  t: TFunction<'scene3d'>
  editorT: TFunction<'scene3dEditor'>
  onSelect: (id: string) => void
  onSpeech: () => void
  onAssign: (slot: Scene3DSlot, capture: SlotSourceCapture, item: ApiOutput | null) => void
  onApplyScene: (updater: Scene3DDocument | ((current: Scene3DDocument) => Scene3DDocument), group?: string) => void
  onBumpGeneration: () => void
  liveSource: () => SlotSourceLive
}) {
  const captureFromLive = (): SlotSourceCapture => {
    const live = liveSource()
    return { generation: live.generation, slotId: slot.id, templateId, workspaceId: workspace }
  }
  return (
    <div className={`rounded-xl border p-3 text-xs text-text-secondary ${selected ? 'border-cyan-300 bg-cyan-400/5' : 'border-border bg-bg-primary'}`}>
      <button type="button" className="block min-h-10 font-semibold text-text-primary" onClick={() => onSelect(slot.id)}>{t(`stage.slot.${slot.slot}`)}</button>
      {slot.media === 'model3d' && <button type="button" className="mb-2 min-h-9 rounded-lg border border-border px-3 text-xs hover:bg-bg-hover" onClick={onSpeech}>{editorT('speech.option')}{slot.speech?.enabled ? ' · ✓' : ''}</button>}
      {slot.media === 'model3d' && selected && <FaceDecalControls slot={slot} workspace={workspace} disabled={editingLocked} title={controlReason(editingLocked, 'disabled.panelLocked')} onChange={faceDecal => onApplyScene(current => patchScene3DSlot(current, slot.id, { faceDecal }))} />}
      {slot.media !== 'screen' && <div className="mt-1">
        <AssetInput
          label={t(`stage.slot.${slot.slot}`)}
          placeholder={t('stage.fromApp')}
          items={slot.media === 'image' ? imageItems : modelItems}
          value={pickerOutputFromSlot(slot.sourceUrl, slot.media, slot.sourceRef)}
          accept={slot.media === 'image' ? 'image/*' : '.glb,model/gltf-binary'}
          optional
          disabled={exporting}
          constraints={{ kinds: slot.media === 'image' ? ['image'] : ['model3d'], maxCount: 1, optional: true }}
          onChoose={item => onAssign(slot, captureFromLive(), item)}
        />
      </div>}
      <Scene3DScreenControls slot={slot} meshes={meshes} nodes={nodes} items={[...imageItems, ...videoItems]} disabled={editingLocked} workspace={workspace}
        onChange={screen => onApplyScene(current => patchScene3DSlot(current, slot.id, { screen }))}
        onApplyToAll={() => onApplyScene(current => applyScreenToAllTvs(current, slot.id))}
        onChoose={item => {
          if (item && item.type !== 'image' && item.type !== 'video') return
          const commit = commitSlotSourceChoice(liveSource(), captureFromLive(), item)
          if (commit.action === 'ignore') return
          onApplyScene(current => {
            const live = current.slots.find(value => value.id === slot.id)
            if (!live?.screen) return current
            return patchScene3DSlot(current, slot.id, { screen: { ...live.screen, sourceUrl: commit.action === 'clear' ? '' : commit.sourceUrl,
              sourceRef: commit.action === 'clear' ? undefined : commit.sourceRef, poseSequence: undefined, media: item?.type === 'video' ? 'video' : 'image' } })
          })
        }}
        onRemove={() => { onBumpGeneration(); onApplyScene(current => ({ ...current, slots: current.slots.filter(value => value.id !== slot.id), camera: current.camera.framing?.targetSlot === slot.id ? { ...current.camera, framing: undefined } : current.camera })) }} />
      <AppearanceControls slot={slot} disabled={editingLocked} onChange={patch => onApplyScene(current => patchScene3DSlot(current, slot.id, patch))} />
      <Scene3DHoldControls slot={slot} slots={slots} disabled={editingLocked}
        onChange={patch => onApplyScene(current => patchScene3DSlot(current, slot.id, patch))} />
      <Scene3DAnimationControls slot={slot} clips={catalogs[slot.id]} duration={duration} disabled={editingLocked}
        onChange={patch => onApplyScene(current => patchScene3DSlot(current, slot.id, patch))} />
      <SlotImageSurfaceControls slot={slot} exporting={exporting} editorT={editorT} onApplyScene={onApplyScene} />
      {slot.slot === 'background' && !slot.surface && (
        <InfiniteBackdropControls
          loop={slot.loop}
          disabled={exporting}
          infiniteLabel={t('stage.infinite')}
          speedLabel={t('stage.loopSpeed')}
          onChange={loop => onApplyScene(current => patchScene3DSlot(current, slot.id, {
            media: 'image',
            loop,
            ...(loop.cylinder && slot.scale > 2 ? { scale: 1 } : {}),
          }))}
        />
      )}
    </div>
  )
}

function InfiniteBackdropControls({
  loop, infiniteLabel, speedLabel, onChange, disabled = false,
}: {
  loop: Scene3DLoop | undefined
  infiniteLabel: string
  speedLabel: string
  onChange: (loop: Scene3DLoop) => void
  disabled?: boolean
}) {
  const speed = loop?.speed ?? 0.18
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      <label className="flex items-center gap-1 text-sm text-text-muted">
        <input aria-label={infiniteLabel}
          type="checkbox"
          data-testid="scene3d-infinite"
          disabled={disabled}
          checked={loop?.cylinder === true}
          onChange={event => onChange({ cylinder: event.target.checked, speed })}
        />
        {infiniteLabel}
      </label>
      {loop?.cylinder === true && numberField(speedLabel, speed, value => onChange({ cylinder: true, speed: value }), 0.01, disabled)}
    </div>
  )
}
