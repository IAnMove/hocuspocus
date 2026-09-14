import { randomUuid } from './uuid'

// A saved scene already has a durable recovery copy. Keep a backup only when
// replacing an unsaved document, including edits made after the last save.
export class SceneHandoffRecovery {
  private savedSnapshot: string | undefined

  markSaved(workspace: string, document: unknown) {
    this.savedSnapshot = JSON.stringify([workspace, document])
  }

  backup(storage: Storage, workspace: string, document: unknown) {
    if (this.savedSnapshot === JSON.stringify([workspace, document])) return
    storage.setItem(`hocuspocus:scene-before-command:${randomUuid()}`, JSON.stringify(document))
  }
}

// A later edit may have replaced this key while the render was in flight.
export function releaseStoredSceneCopy(storage: Storage, key: string, savedCopy: string) {
  if (storage.getItem(key) === savedCopy) storage.removeItem(key)
}
