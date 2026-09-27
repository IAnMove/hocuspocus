import { scene3dCopy } from './copy.ts'
import { cloneScene3DDocument } from './document.ts'
import type { Scene3DStageHandle } from './Scene3DStage.tsx'
import type { Scene3DDocument } from './types.ts'

export function canMutateWorld3DScene(exporting: boolean): boolean {
  return !exporting
}

export function paintWorld3DExportFrame(
  handle: Pick<Scene3DStageHandle, 'paint'>,
  snapshot: Scene3DDocument,
  seconds: number,
): HTMLCanvasElement {
  const canvas = handle.paint(seconds, snapshot)
  if (!canvas) throw new Error(scene3dCopy('stage.stageNotReady'))
  return canvas
}

export function startWorld3DExport(
  handle: Pick<Scene3DStageHandle, 'beginExport' | 'setExportSize' | 'setExportQuality'>,
  document: Scene3DDocument,
  size: { width: number; height: number },
): Scene3DDocument {
  const snapshot = cloneScene3DDocument(document)
  handle.beginExport(snapshot)
  handle.setExportSize(size.width, size.height)
  handle.setExportQuality(true)
  return snapshot
}

export function finishWorld3DExport(
  handle: Pick<Scene3DStageHandle, 'endExport' | 'restoreSize' | 'setExportQuality'>,
): void {
  handle.setExportQuality(false)
  handle.endExport()
  handle.restoreSize()
}
