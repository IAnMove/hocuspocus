export const VIDEO_EDITOR_REPLACEMENT_TARGET_KEY = 'maestro-video-editor-replacement-target-v1'
export const VIDEO_EDITOR_REPLACEMENT_RESULT_KEY = 'maestro-video-editor-replacement-result-v1'

export interface VideoEditorReplacementTarget {
  clipId: string
  clipIndex: number
  originalName: string
  outputName: string
  requestedAt: number
}

export interface VideoEditorReplacementResult {
  clipId: string
  clipIndex: number
  outputName: string
  source: string
  selectedAt: number
}

function readStored<T>(key: string): T | null {
  try {
    const value = JSON.parse(window.localStorage.getItem(key) || 'null')
    return value && typeof value === 'object' ? value as T : null
  } catch {
    return null
  }
}

export function readVideoEditorReplacementTarget(): VideoEditorReplacementTarget | null {
  const target = readStored<VideoEditorReplacementTarget>(VIDEO_EDITOR_REPLACEMENT_TARGET_KEY)
  if (!target || typeof target.clipId !== 'string' || !Number.isInteger(target.clipIndex)) return null
  return target
}

export function writeVideoEditorReplacementTarget(target: VideoEditorReplacementTarget): void {
  window.localStorage.setItem(VIDEO_EDITOR_REPLACEMENT_TARGET_KEY, JSON.stringify(target))
  window.localStorage.removeItem(VIDEO_EDITOR_REPLACEMENT_RESULT_KEY)
}

export function clearVideoEditorReplacementTarget(): void {
  window.localStorage.removeItem(VIDEO_EDITOR_REPLACEMENT_TARGET_KEY)
}

export function writeVideoEditorReplacementResult(result: VideoEditorReplacementResult): void {
  window.localStorage.setItem(VIDEO_EDITOR_REPLACEMENT_RESULT_KEY, JSON.stringify(result))
  clearVideoEditorReplacementTarget()
}

export function readVideoEditorReplacementResult(): VideoEditorReplacementResult | null {
  const result = readStored<VideoEditorReplacementResult>(VIDEO_EDITOR_REPLACEMENT_RESULT_KEY)
  if (!result || typeof result.clipId !== 'string' || typeof result.source !== 'string') return null
  return result
}

export function clearVideoEditorReplacementResult(): void {
  window.localStorage.removeItem(VIDEO_EDITOR_REPLACEMENT_RESULT_KEY)
}

export function outputNameFromEditorClip(source: string, fallbackName: string): string {
  try {
    const parsed = new URL(source, window.location.origin)
    const marker = '/api/v1/file/'
    const markerIndex = parsed.pathname.indexOf(marker)
    if (markerIndex >= 0) {
      const storedName = parsed.pathname.slice(markerIndex + marker.length)
      if (storedName) return decodeURIComponent(storedName)
    }
  } catch {
    // Fall back to the display name below for old or non-URL drafts.
  }
  return fallbackName
}
