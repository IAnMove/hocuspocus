import { normalizeVideoJsDocument } from './document.ts'
import type { VideoJsDocument } from './types.ts'

const PREFIX = 'hocuspocus.videojs.draft.v1'

export function videoJsDraftKey(workspace: string | null | undefined): string {
  return `${PREFIX}:${workspace || 'default'}`
}

/** Per-browser draft only. The MP4 sidecar is the durable, shared record. */
export function readVideoJsDraft(workspace: string | null | undefined): VideoJsDocument | null {
  try {
    const raw = window.localStorage.getItem(videoJsDraftKey(workspace))
    return raw ? normalizeVideoJsDocument(JSON.parse(raw)) : null
  } catch {
    return null
  }
}

export function writeVideoJsDraft(workspace: string | null | undefined, document: VideoJsDocument): boolean {
  try {
    window.localStorage.setItem(videoJsDraftKey(workspace), JSON.stringify(document))
    return true
  } catch {
    return false
  }
}

export function downloadVideoJsDocument(document: VideoJsDocument): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], { type: 'application/json' }))
  const link = window.document.createElement('a')
  link.href = url
  link.download = `${document.title.replace(/[^\w-]+/g, '-').slice(0, 60) || 'video'}.videojs.json`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function readVideoJsFile(file: File): Promise<VideoJsDocument> {
  if (file.size > 2 * 1024 * 1024) throw new Error('Video JS files must be under 2 MB')
  return normalizeVideoJsDocument(JSON.parse(await file.text()))
}
