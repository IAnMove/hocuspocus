import type { ApiOutput } from '../../api/outputs'
import { canMutateWorld3DScene } from './exportLock.ts'
import { exportWorld3DDocument } from './exportFlow.ts'
import { commitSlotSourceChoice, type SlotSourceCapture } from './slotSource.ts'
import { patchScene3DSlot } from './templates.ts'
import type { Scene3DClipCatalogEntry, Scene3DDocument, Scene3DSlot } from './types.ts'
import type { Scene3DStageHandle } from './Scene3DStage.tsx'

export function applyAssignedSlotSource(
  slot: Scene3DSlot,
  capture: SlotSourceCapture,
  item: ApiOutput | null,
  exporting: boolean,
  revoke: (url: string) => void,
  applyScene: (updater: (current: Scene3DDocument) => Scene3DDocument) => void,
  setCatalogs: (update: (current: Record<string, Scene3DClipCatalogEntry[]>) => Record<string, Scene3DClipCatalogEntry[]>) => void,
) {
  const commit = commitSlotSourceChoice({ ...capture, exporting }, capture, item)
  if (commit.action === 'ignore' || !canMutateWorld3DScene(exporting)) return
  revoke(slot.sourceUrl)
  if (commit.action === 'clear') {
    applyScene(current => patchScene3DSlot(current, slot.id, { sourceUrl: '', sourceRef: undefined, clip: null, speech: undefined }))
  } else {
    applyScene(current => patchScene3DSlot(current, slot.id, {
      sourceUrl: commit.sourceUrl,
      sourceRef: commit.sourceRef,
      speech: slot.speech ? { ...slot.speech, face: undefined, atlas: undefined } : undefined,
      media: commit.media,
      clip: commit.clip,
    }))
  }
  setCatalogs(current => {
    const next = { ...current }
    delete next[slot.id]
    return next
  })
}

export async function exportWorkspaceDocument(
  stage: Scene3DStageHandle | null,
  document: Scene3DDocument,
  workspace: string,
  playing: boolean,
  exporting: boolean,
  copy: (key: string, values?: Record<string, string | number>) => string,
  onNote: (note: string) => void,
  onExporting: (value: boolean) => void,
  setAbort: (abort: AbortController | null) => void,
) {
  if (!stage || exporting || playing) return
  const abort = new AbortController()
  setAbort(abort)
  onExporting(true)
  onNote(copy('stage.exporting'))
  try {
    const result = await exportWorld3DDocument(stage, document, workspace, (index, total) => {
      onNote(copy('stage.exportProgress', { index, total }))
    }, abort.signal)
    ;(window as Window & { __world3dLastMp4?: Blob }).__world3dLastMp4 = result.blob
    if (result.saved) onNote(copy('stage.exported', { name: result.saved.name }))
    else onNote(result.error?.message ?? copy('stage.exportFailed'))
  } catch (error) {
    const aborted = abort.signal.aborted || (error instanceof DOMException && error.name === 'AbortError')
    onNote(aborted ? copy('stage.exportCancelled') : error instanceof Error ? error.message : copy('stage.exportFailed'))
  } finally {
    setAbort(null)
    onExporting(false)
  }
}
