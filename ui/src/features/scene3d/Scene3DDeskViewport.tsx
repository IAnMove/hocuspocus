import { useUiTranslation } from '../../i18n'
import { KineticTextOverlay } from '../../components/common/KineticTextOverlay'
import { SceneFxOverlay } from '../sceneFx/SceneFxOverlay'
import { worldSfxAudioCues } from '../sceneFx/world'
import { PROP_DRAG_TYPE, type LibraryProp } from './propLibrary'
import { defaultSpeech } from './speech/types'
import { LipsPickOverlay } from './speech/LipsPickOverlay'
import { Scene3DInteraction } from './Scene3DInteraction'
import { Scene3DPreview } from './Scene3DPreview'
import { Scene3DEditCameraBar } from './Scene3DEditCameraBar'
import { Scene3DViewportTools } from './Scene3DViewportTools'
import { patchScene3DSlot } from './templates.ts'
import { applyScene3DGizmoPatch } from './documentHistory.ts'
import { Scene3DStage, type Scene3DStageHandle } from './Scene3DStage.tsx'
import type { Scene3DDeskModel } from './scene3dDeskModel'
import type { DragEvent, MutableRefObject } from 'react'

export function Scene3DDeskViewport({ model, stage }: {
  model: Scene3DDeskModel
  stage: MutableRefObject<Scene3DStageHandle | null>
}) {
  const { t } = useUiTranslation('scene3d')
  const { t: editorT } = useUiTranslation('scene3dEditor')
  const selected = model.selected
  const pickKey = selected ? `${model.generation}/${selected.id}/${selected.sourceUrl}` : ''
  return (
    <div
      className="flex h-full min-h-0 flex-col"
      onDragOver={event => { if (event.dataTransfer.types.includes(PROP_DRAG_TYPE)) event.preventDefault() }}
      onDrop={event => acceptPropDrop(event, model)}
    >
      <Scene3DPreview width={model.sceneDoc.width} height={model.sceneDoc.height} fill>
        <Scene3DInteraction
          enabled={!model.playing && !model.exporting && (Boolean(model.selectedWorldSfxId) || Boolean(selected))}
          width={model.sceneDoc.width}
          height={model.sceneDoc.height}
          onMode={model.setTransformMode}
        >
          <Scene3DStage
            key={model.generation}
            ref={stage}
            document={model.sceneDoc}
            sceneSeconds={model.seconds}
            selectedId={model.selectedId}
            selectedWorldSfxId={model.selectedWorldSfxId}
            transformMode={model.transformMode}
            editing={!model.playing && !model.exporting}
            freeView={model.freeView}
            onSelect={model.onStageSelect}
            onTransform={(id, patch) => model.applyScene(current => applyScene3DGizmoPatch(current, id, patch, model.seconds), `drag:${id}`)}
            onSlotClips={(slotId, clips) => model.setCatalogs(current => ({ ...current, [slotId]: clips }))}
            onSlotMeshes={(slotId, meshes, nodes) => model.setScreenTargets(current => ({ ...current, [slotId]: { meshes, nodes } }))}
          />
          <SceneFxOverlay cues={model.sceneDoc.sfx} soundCues={[...(model.sceneDoc.sfx ?? []), ...worldSfxAudioCues(model.sceneDoc.worldSfx)]} seconds={model.seconds} width={model.sceneDoc.width} height={model.sceneDoc.height} duration={model.sceneDoc.duration} playing={model.playing} speed={model.speed} getSource={() => stage.current?.canvas() ?? null} />
          <KineticTextOverlay cues={model.sceneDoc.texts} seconds={model.seconds} width={model.sceneDoc.width} height={model.sceneDoc.height} />
          <LipsLayer model={model} pickKey={pickKey} stage={stage} />
          {model.sceneDoc.clipNumber && <div className="pointer-events-none absolute right-3 top-3 z-10 rounded bg-black/80 px-3 py-2 font-mono text-sm text-cyan-50">CLIP {String(model.sceneDoc.clipNumber).padStart(2, '0')}</div>}
        </Scene3DInteraction>
        <Scene3DViewportTools
          mode={model.transformMode}
          disabled={model.editingLocked}
          onMode={model.setTransformMode}
          caption={`${t('stage.badge')} · ${editorT(`template.${model.sceneDoc.templateId}.title`)}`}
          captionNote={t('stage.previewQuality')}
        />
        <Scene3DEditCameraBar model={model} />
      </Scene3DPreview>
    </div>
  )
}

function LipsLayer({ model, pickKey, stage }: {
  model: Scene3DDeskModel
  pickKey: string
  stage: MutableRefObject<Scene3DStageHandle | null>
}) {
  const selected = model.selected
  if (!model.speechVisible || model.playing || model.exporting || !selected || model.pickTarget !== pickKey) return null
  return (
    <LipsPickOverlay onCancel={() => model.setPickTarget(undefined)} onPick={(x, y) => {
      const face = stage.current?.pickFace?.(selected.id, x, y, selected.speech?.face)
      if (!face) return false
      model.applyScene(current => patchScene3DSlot(current, selected.id, {
        speech: { ...defaultSpeech(), ...selected.speech, face, enabled: true, eyes: selected.speech?.face ? selected.speech.eyes : false, clean: selected.speech?.face ? selected.speech.clean : false },
      }))
      model.setPickTarget(undefined)
      return true
    }} />
  )
}

function acceptPropDrop(event: DragEvent, model: Scene3DDeskModel) {
  const raw = event.dataTransfer.getData(PROP_DRAG_TYPE)
  if (!raw || model.editingLocked) return
  event.preventDefault()
  try {
    const prop = JSON.parse(raw) as LibraryProp
    if (prop.approved && prop.heightM > 0) model.addProp(prop)
  } catch { /* Ignore foreign drag data. */ }
}
