import { useUiTranslation } from '../../i18n'
import { KineticTextControls } from '../../components/common/KineticTextControls'
import { SceneFxControls } from '../sceneFx/SceneFxControls'
import { WorldSfxControls } from '../sceneFx/WorldSfxControls'
import { ExportReviewPanel } from '../render/ExportReviewPanel.tsx'
import { AtmosClearingControls } from './AtmosClearingControls.tsx'
import { CinematicControls, RenderLookControls } from './CinematicControls'
import { ComicTransitionPanel } from './ComicTransitionPanel'
import { ExampleDownloads } from './ExampleDownloads'
import { MotionLabControls } from './motionlab/controls'
import { PixelWorldControls } from './PixelWorldControls'
import { addTv } from './pixel/pixelEdits'
import { Scene3DDocumentControls } from './Scene3DDocumentControls'
import { Scene3DFramingControls } from './Scene3DFramingControls'
import { Scene3DGeometryReview } from './Scene3DGeometryReview.tsx'
import { Scene3DMotionControls } from './Scene3DMotionControls'
import { Scene3DRoomCameraPicker } from './Scene3DRoomCameraPicker'
import { Scene3DSlotCard } from './Scene3DSlotCard'
import { Scene3DTransformPanel } from './Scene3DTransformPanel'
import { SceneObjectInspector } from './SceneObjectInspector.tsx'
import { Scene3DSpeakerControls } from './speech/Scene3DSpeakerControls'
import { Scene3DSpeechSelector } from './speech/Scene3DSpeechSelector'
import { Scene3DSpeechStatus } from './speech/Scene3DSpeechStatus'
import { Scene3DSoundtrackControls } from './speech/Scene3DSoundtrackControls'
import { speechEnd } from './speech/timeline'
import { withRoomCamera } from './roomCamera'
import { exampleCollections } from './templateCatalog'
import { patchScene3DSlot } from './templates.ts'
import type { Scene3DCameraFamily, Scene3DDocument, Scene3DSlot } from './types.ts'
import type { Scene3DDeskModel } from './scene3dDeskModel'

const FAMILIES = ['fixed', 'establishment', 'orbit', 'follow', 'pursuit', 'side', 'front', 'chase', 'hood', 'wing', 'product', 'reveal', 'encounter', 'musical'] as const satisfies readonly Scene3DCameraFamily[]

export function Scene3DDeskInspector({ model }: { model: Scene3DDeskModel }) {
  return (
    <div className="space-y-3 p-2">
      <Scene3DDeskStatus model={model} />
      {model.selected && <Scene3DDeskObject model={model} slot={model.selected} />}
      <Scene3DDeskSfx model={model} objectButton={Boolean(model.selected)} />
      <SceneObjectInspector
        document={model.sceneDoc}
        selectedId={model.selectedId}
        locked={model.editingLocked}
        saveState={model.session.saveState}
        canUndo={model.session.canUndo}
        canRedo={model.session.canRedo}
        conflict={model.session.conflict}
        showHistory={false}
        showPreview={false}
        showPose={false}
        allowEmpty
        onChange={(next, group) => model.applyScene(next, group)}
        onUndo={model.session.undo}
        onRedo={model.session.redo}
        onCheckpoint={model.session.checkpoint}
        onResolveConflict={model.session.resolveConflict}
      />
      <Scene3DDeskScene model={model} />
    </div>
  )
}

function Scene3DDeskStatus({ model }: { model: Scene3DDeskModel }) {
  const { t } = useUiTranslation('scene3dEditor')
  return (
    <div className="space-y-3">
      <ExampleDownloads required={exampleCollections(model.sceneDoc)} disabled={model.editingLocked} onInstalled={model.onExamplesInstalled} />
      {model.sceneDoc.production && <p className="rounded-lg border border-border bg-bg-secondary p-3 text-sm" data-testid="speech-production-origin">
        {t(`speech.kind.${model.sceneDoc.production.kind}`)} · {model.sceneDoc.production.title}
        <span className="mt-1 block text-xs text-text-muted">{t('speech.productionReady')}</span>
        <button type="button" className="mt-2 underline" disabled={model.editingLocked} onClick={model.restorePreviousShot}>{t('speech.previousShot')}</button>
      </p>}
      <Scene3DSpeechStatus document={model.sceneDoc} seconds={model.seconds} />
      <Scene3DSoundtrackControls tracks={model.sceneDoc.soundtrack} disabled={model.editingLocked} onChange={soundtrack => model.applyScene(current => ({ ...current, soundtrack }))} />
      <Scene3DSpeechSelector slots={model.sceneDoc.slots} selected={model.selected} open={model.speechOpen} onToggle={() => { model.setPickTarget(undefined); model.setSpeechOpen(open => !open) }} onSelect={model.selectSlot} />
    </div>
  )
}

function Scene3DDeskObject({ model, slot }: { model: Scene3DDeskModel; slot: Scene3DSlot }) {
  const { t } = useUiTranslation('scene3d')
  const { t: editorT } = useUiTranslation('scene3dEditor')
  return (
    <div className="space-y-3">
      <Scene3DTransformPanel
        slot={slot}
        mode={model.transformMode}
        disabled={model.editingLocked}
        showModes={false}
        onMode={model.setTransformMode}
        onChange={patch => model.applyScene(current => patchScene3DSlot(current, slot.id, patch))}
        onReset={model.resetSelectedPose}
      />
      <Scene3DSlotCard
        slot={slot}
        selected
        catalogs={model.catalogs}
        slots={model.sceneDoc.slots}
        duration={model.sceneDoc.duration}
        templateId={model.sceneDoc.templateId}
        workspace={model.workspace}
        exporting={model.exporting}
        editingLocked={model.editingLocked}
        imageItems={model.imageItems}
        modelItems={model.modelItems}
        videoItems={model.videoItems}
        meshes={model.screenTargets[slot.id]?.meshes ?? []}
        nodes={model.screenTargets[slot.id]?.nodes ?? []}
        t={t}
        editorT={editorT}
        onSelect={model.selectSlot}
        onSpeech={() => {
          model.selectSlot(slot.id)
          model.setSpeechOpen(true)
          window.requestAnimationFrame(() => window.document.getElementById('world3d-speech-inspector')?.scrollIntoView({ block: 'nearest' }))
        }}
        onAssign={model.assignChoice}
        onApplyScene={model.applyScene}
        onBumpGeneration={model.bumpGeneration}
        liveSource={() => ({ ...model.liveSource(), slotId: slot.id })}
      />
      <SlotMotion model={model} slot={slot} />
      {model.speechVisible && <div id="world3d-speech-inspector" className="min-w-0">
        <Scene3DSpeakerControls
          key={`${model.workspace}/${model.generation}/${slot.id}/${slot.sourceUrl}`}
          slot={slot}
          workspace={model.workspace}
          disabled={model.editingLocked}
          onPick={() => { model.setPlaying(false); model.setPickTarget(`${model.generation}/${slot.id}/${slot.sourceUrl}`) }}
          calibrate={profile => model.stageRef.current?.facePlacement?.(slot.id, profile)}
          onChange={speech => model.applyScene(current => sameSource(current, slot) ? patchScene3DSlot(current, slot.id, { speech }) : current)}
          onImport={patch => model.applyScene(current => sameSource(current, slot) ? patchScene3DSlot(current, slot.id, patch) : current)}
          onFit={duration => model.applyScene(current => fitSpeechDuration(current, duration))}
        />
      </div>}
    </div>
  )
}

function Scene3DDeskSfx({ model, objectButton }: { model: Scene3DDeskModel; objectButton: boolean }) {
  const { t } = useUiTranslation('scene3dEditor')
  return (
    <div className="space-y-2">
      {objectButton && <button type="button" data-testid="scene3d-object-sfx" disabled={model.editingLocked} onClick={() => model.openPicker('world')} className="min-h-10 rounded-lg border border-violet-400/40 px-3 text-xs text-text-primary disabled:opacity-40">{t('desk.objectSfx')}</button>}
      <WorldSfxControls
        cues={model.sceneDoc.worldSfx}
        duration={model.sceneDoc.duration}
        selectedId={model.selectedWorldSfxId}
        disabled={model.editingLocked}
        showKindGrid={false}
        onSelect={id => { model.setPickTarget(undefined); model.setSelectedWorldSfxId(id) }}
        onChange={worldSfx => model.applyScene(current => ({ ...current, worldSfx }))}
        onDemo={model.onDemo}
      />
    </div>
  )
}

function Scene3DDeskScene({ model }: { model: Scene3DDeskModel }) {
  const { t } = useUiTranslation('scene3d')
  const { t: editorT } = useUiTranslation('scene3dEditor')
  const doc = model.sceneDoc
  return (
    <div className="space-y-3">
      <Scene3DDocumentControls section="timing" document={doc} disabled={model.editingLocked} workspace={model.workspace} preview={model.preview} identity={model.session.identity} onChange={next => { model.applyScene(next); model.setFrame(0) }} onLoad={model.loadDocument} onSaved={model.acknowledgeSave} />
      <RenderLookControls document={doc} disabled={model.editingLocked} onChange={look => model.applyScene(current => ({ ...current, ...look }))} />
      <CinematicControls environment={doc.environment} disabled={model.editingLocked} onChange={environment => model.applyScene(current => ({ ...current, environment }))} />
      <AtmosClearingControls document={doc} disabled={model.exporting} label={key => editorT(key as 'atmos.time')} onChange={atmos => model.applyScene(current => ({ ...current, atmos }))} />
      <PixelWorldControls pixelWorld={doc.pixelWorld} dressing={doc.dressing} tvs={doc.slots.filter(slot => slot.screen?.style === 'crt').length} slots={doc.slots.length} disabled={model.editingLocked} onChange={patch => model.applyScene(current => ({ ...current, ...patch }))} onAddTv={() => model.applyScene(current => addTv(current))} />
      <MotionLabControls document={doc} disabled={model.editingLocked} onChange={motionLab => model.applyScene(current => ({ ...current, motionLab }))} />
      <SceneFxControls cues={doc.sfx} duration={doc.duration} disabled={model.editingLocked} showShowcase={false} onChange={sfx => model.applyScene(current => ({ ...current, sfx }))} onShowcase={model.onShowcase} />
      <Scene3DFramingControls framing={doc.camera.framing} slots={doc.slots} disabled={model.editingLocked || doc.camera.family === 'fixed'} onChange={framing => model.applyScene(current => ({ ...current, camera: { ...current.camera, framing } }))} />
      <ComicTransitionPanel workspace={model.workspace || undefined} disabled={model.editingLocked} />
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-sm text-text-primary">{editorT('camera')}
          <select disabled={model.exporting} value={doc.camera.family} onChange={event => model.applyScene(current => ({ ...current, camera: { ...current.camera, family: event.target.value as Scene3DCameraFamily, framing: undefined } }))} className="min-h-11 rounded-lg border border-border bg-bg-primary px-3 text-xs disabled:opacity-40">
            {FAMILIES.map(family => <option key={family} value={family}>{t(`stage.family.${family}`)}</option>)}
          </select>
        </label>
        <Scene3DRoomCameraPicker document={doc} disabled={model.exporting} onChange={id => model.applyScene(current => withRoomCamera(current, id))} />
      </div>
      {doc.dressing === 'workshop' && <label className="flex items-center gap-2 text-xs">{editorT('travel.screen')}<select disabled={model.exporting} value={doc.workshopScreen ?? 'code'} onChange={event => model.applyScene(current => ({ ...current, workshopScreen: event.target.value as 'code' | 'error' | 'success' }))} className="min-h-10 rounded border border-border bg-bg-tertiary px-2">{(['code', 'error', 'success'] as const).map(state => <option key={state} value={state}>{editorT(`travel.${state}`)}</option>)}</select></label>}
      <Scene3DGeometryReview stageRef={model.stageRef} document={doc} seconds={model.seconds} disabled={model.exporting} onSeek={model.seek} />
      {!model.selectedId && <UnselectedMotion model={model} />}
      <KineticTextControls cues={doc.texts} duration={doc.duration} disabled={model.editingLocked} onChange={texts => model.applyScene(current => ({ ...current, texts }))} />
      <details className="rounded-lg border border-border p-2">
        <summary className="cursor-pointer text-sm font-semibold">{t('inspector.advanced')}</summary>
        <div className="mt-2">
          <Scene3DDocumentControls section="files" document={doc} disabled={model.editingLocked} workspace={model.workspace} preview={model.preview} identity={model.session.identity} onChange={next => { model.applyScene(next); model.setFrame(0) }} onLoad={model.loadDocument} onSaved={model.acknowledgeSave} />
        </div>
      </details>
      <ExportReviewPanel review={model.receiptReview} duration={doc.duration} onSeek={model.seek} />
      <p className="text-xs text-text-muted">{t('stage.exportQualityHint')}</p>
      {model.clipIssue && <p className="text-xs text-red-300">{model.clipIssue}</p>}
      {model.exportNote && <p className="text-xs text-cyan-100" data-testid="world3d-export-note">{model.exportNote}</p>}
      <p className="text-xs text-text-muted">{doc.templateId === 'run-loop' ? t('stage.runHelp') : t('stage.help')}</p>
    </div>
  )
}

function SlotMotion({ model, slot }: { model: Scene3DDeskModel; slot: Scene3DSlot }) {
  if (slot.media === 'image' && slot.surface !== 'cutout') return null
  return (
    <Scene3DMotionControls
      slot={slot}
      duration={model.sceneDoc.duration / model.speed}
      disabled={model.editingLocked}
      onChange={patch => model.applyScene(current => patchScene3DSlot(current, slot.id, patch))}
      walk={model.walkFor(slot)}
    />
  )
}

function UnselectedMotion({ model }: { model: Scene3DDeskModel }) {
  const slot = model.sceneDoc.slots.find(item => item.media === 'model3d')
  if (!slot) return null
  return <SlotMotion model={model} slot={slot} />
}

function sameSource(current: Scene3DDocument, slot: Scene3DSlot) {
  return current.slots.find(item => item.id === slot.id)?.sourceUrl === slot.sourceUrl
}

function fitSpeechDuration(current: Scene3DDocument, duration: number): Scene3DDocument {
  const spoken = current.slots.map(item => item.speech?.enabled ? speechEnd(item.speech) : 0)
  const tracks = (current.soundtrack ?? []).map(track => track.end ?? 0)
  return { ...current, duration: Math.min(600, Math.max(duration, ...spoken, ...tracks)) }
}
