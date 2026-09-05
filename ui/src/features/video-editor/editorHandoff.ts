export const VIDEO_EDITOR_PENDING_SOURCE_KEY = 'maestro-video-editor-pending-source'

export interface VideoEditorPendingSource {
  name?: string
  url: string
}

/** Filename the editor backend can resolve. Gallery URLs include ?workspace=. */
export function editorSourcePath(urlOrName: string): string {
  const raw = String(urlOrName || '').trim()
  if (!raw) return raw
  const withoutHash = raw.split('#')[0]
  const withoutQuery = withoutHash.split('?')[0]
  const last = withoutQuery.split('/').pop() || withoutQuery
  try {
    return decodeURIComponent(last)
  } catch {
    return last
  }
}

export function writeVideoEditorPendingSource(source: VideoEditorPendingSource): void {
  try {
    window.localStorage.setItem(VIDEO_EDITOR_PENDING_SOURCE_KEY, JSON.stringify(source))
  } catch {
    // A browser storage failure must not prevent the user from continuing.
  }
}
