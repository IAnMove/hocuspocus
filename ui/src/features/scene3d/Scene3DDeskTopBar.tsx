import { useUiTranslation } from '../../i18n'
import { RenderQualityPicker } from '../render/RenderQualityPicker'
import { Scene3DDocumentControls } from './Scene3DDocumentControls'
import type { Scene3DDeskModel } from './scene3dDeskModel'

export function Scene3DDeskTopBar({ model }: { model: Scene3DDeskModel }) {
  const { t } = useUiTranslation('scene3d')
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Scene3DDocumentControls
        section="library"
        document={model.sceneDoc}
        disabled={model.editingLocked}
        workspace={model.workspace}
        preview={model.preview}
        identity={model.session.identity}
        onChange={next => { model.applyScene(next); model.setFrame(0) }}
        onLoad={model.loadDocument}
        onSaved={model.acknowledgeSave}
      />
      <DeskHistory model={model} />
      <RenderQualityPicker
        width={model.sceneDoc.width}
        height={model.sceneDoc.height}
        fps={model.fps}
        duration={model.sceneDoc.duration}
        disabled={model.exporting}
        capabilitiesUrl="/api/v1/scenes/world3d/export/capabilities"
        onChange={model.setRenderChoice}
      />
      <button
        type="button"
        data-testid="world3d-export"
        disabled={model.editingLocked || Boolean(model.clipIssue)}
        onClick={() => void model.exportScene()}
        className="min-h-11 rounded-lg border border-cyan-400/50 bg-cyan-400/10 px-4 text-xs font-semibold text-cyan-100 disabled:opacity-40"
      >
        {model.exporting ? t('stage.exporting') : t('stage.export')}
      </button>
      {model.exporting && <button
        type="button"
        data-testid="world3d-export-cancel"
        onClick={model.abortExport}
        className="min-h-11 rounded-lg border border-amber-400/50 bg-amber-400/10 px-4 text-xs font-semibold text-amber-100"
      >{t('stage.exportCancel')}</button>}
      {model.topBarExtra}
    </div>
  )
}

function DeskHistory({ model }: { model: Scene3DDeskModel }) {
  const { t } = useUiTranslation('scene3d')
  const locked = model.editingLocked
  return (
    <div className="flex flex-wrap items-center gap-2">
      <button type="button" data-testid="scene3d-history-undo" className="min-h-11 rounded-lg border border-border px-3 text-xs" disabled={locked || !model.session.canUndo} onClick={model.session.undo}>{t('history.undo')}</button>
      <button type="button" data-testid="scene3d-history-redo" className="min-h-11 rounded-lg border border-border px-3 text-xs" disabled={locked || !model.session.canRedo} onClick={model.session.redo}>{t('history.redo')}</button>
      <button type="button" data-testid="scene3d-history-checkpoint" className="min-h-11 rounded-lg border border-border px-3 text-xs" disabled={locked} onClick={model.session.checkpoint}>{t('history.checkpoint')}</button>
      <p role="status" data-testid="scene3d-save-state" className="text-xs text-text-muted">{t(`history.${model.session.saveState}`)}</p>
    </div>
  )
}
