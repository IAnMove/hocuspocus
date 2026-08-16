export const VIDEO_EDITOR_PENDING_SOURCE_KEY = 'maestro-video-editor-pending-source'

export interface VideoEditorPendingSource {
  name?: string
  url: string
}

export function writeVideoEditorPendingSource(source: VideoEditorPendingSource): void {
  try {
    window.localStorage.setItem(VIDEO_EDITOR_PENDING_SOURCE_KEY, JSON.stringify(source))
  } catch {
    // A browser storage failure must not prevent the user from continuing.
  }
}
