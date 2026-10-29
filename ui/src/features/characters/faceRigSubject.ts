/** A captured view or an uploaded subject. Blob and data previews are not saved images yet. */

export interface FaceRigViewRef {
  id: string
  url?: string
  filename?: string
}

export interface FaceRigUploadRef {
  path?: string
  file?: unknown
}

export function faceRigHasSubject(
  views: readonly FaceRigViewRef[],
  refs: readonly FaceRigUploadRef[],
  selectedViewId: string | null,
): boolean {
  const captured = views.find(view => view.id === selectedViewId)
    ?? views.find(view => view.id === 'front')
    ?? views[0]
  const source = captured?.url || (captured?.filename ? `file:${captured.filename}` : '')
  if (source && !source.startsWith('blob:') && !source.startsWith('data:')) return true
  const subject = refs[0]
  return Boolean(subject && (subject.path || subject.file))
}
