import type { ShotLibraryProps } from './Scene3DShotLibrary'
import type { Scene3DDeskModel } from './scene3dDeskModel'

/** What the shot library needs from the desk, shared by the top bar and the outline. */
export function deskShotLibraryProps(model: Scene3DDeskModel): Omit<ShotLibraryProps, 'onClose'> {
  return {
    document: model.sceneDoc,
    userTemplateId: model.selectedUserTemplateId,
    applyDisabled: model.exporting,
    editingLocked: model.editingLocked,
    keepAssets: model.keepAssets,
    onKeepAssets: model.setKeepAssets,
    onTemplate: model.mountTemplate,
    onUserTemplate: model.mountUserTemplate,
    workspace: model.workspace,
    preview: model.preview,
  }
}
