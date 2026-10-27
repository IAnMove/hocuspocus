import { useUiTranslation } from '../../i18n'
import { Scene3DObjectList } from './Scene3DObjectList'
import { Scene3DShotLibraryCard } from './Scene3DShotLibraryCard'
import type { Scene3DDeskModel } from './scene3dDeskModel'

export function Scene3DDeskOutline({ model }: { model: Scene3DDeskModel }) {
  const { t } = useUiTranslation('scene3dEditor')
  const full = model.editingLocked || model.sceneDoc.slots.length >= 64
  return (
    <div className="space-y-3 p-2">
      <div className="flex flex-wrap gap-2">
        <button type="button" data-testid="scene3d-desk-scene" aria-pressed={model.selectedId === ''} onClick={() => model.selectSlot('')} className="min-h-10 rounded-lg border border-border px-3 text-xs text-text-primary">{t('desk.scene')}</button>
        <button type="button" data-testid="scene3d-desk-add" disabled={model.editingLocked} onClick={() => model.openPicker('all')} className="min-h-10 rounded-lg border border-cyan-400/50 px-3 text-xs text-text-primary disabled:opacity-40">{t('desk.add')}</button>
        <button type="button" data-testid="scene3d-desk-new-object" disabled={model.editingLocked} onClick={() => model.openPicker('prop')} className="min-h-10 rounded-lg border border-border px-3 text-xs text-text-primary disabled:opacity-40">{t('props.new')}</button>
        <button type="button" disabled={full} onClick={model.addScreen} className="min-h-10 rounded-lg border border-border px-3 text-xs text-text-primary disabled:opacity-40">{t('screens.add')}</button>
      </div>
      <Scene3DShotLibraryCard
        document={model.sceneDoc}
        userTemplateId={model.selectedUserTemplateId}
        applyDisabled={model.exporting}
        editingLocked={model.editingLocked}
        keepAssets={model.keepAssets}
        onKeepAssets={model.setKeepAssets}
        onTemplate={model.mountTemplate}
        onUserTemplate={model.mountUserTemplate}
        workspace={model.workspace}
        preview={model.preview}
      />
      <Scene3DObjectList slots={model.sceneDoc.slots} selectedId={model.selectedWorldSfxId ? undefined : model.selectedId || undefined} onSelect={model.selectSlot} />
      {model.selected?.slot === 'prop' && <button type="button" disabled={model.editingLocked} className="min-h-11 rounded-lg border border-border px-3 text-xs" onClick={model.removeSelected}>{t('props.remove')}</button>}
    </div>
  )
}
