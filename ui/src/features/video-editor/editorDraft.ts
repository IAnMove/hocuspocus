import * as api from '../../api/client'
import {
  editorClipRecoveryMessage,
  normalizeEditorClips,
  type EditorClip,
} from './editorClipNormalization'

export interface ResolutionOption {
  label: string
  width: number
  height: number
}

export const RESOLUTIONS: ResolutionOption[] = [
  { label: 'Landscape 480p', width: 864, height: 480 },
  { label: 'Landscape 720p', width: 1280, height: 720 },
  { label: 'Landscape 1080p', width: 1920, height: 1080 },
  { label: 'Portrait 480p', width: 480, height: 864 },
  { label: 'Portrait 720p', width: 720, height: 1280 },
  { label: 'Portrait 1080p', width: 1080, height: 1920 },
  { label: 'Square 1080p', width: 1080, height: 1080 },
  { label: 'Classic 4:3', width: 1440, height: 1080 },
]

export const VIDEO_EDITOR_DRAFT_KEY = 'maestro-video-editor-draft-v1'

export function clipId(): string {
  return `clip-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}

export function videoEditorDraftStorageKey(workspace: string | null | undefined): string {
  return `${VIDEO_EDITOR_DRAFT_KEY}:${encodeURIComponent(workspace || 'default')}`
}

function parseEditorDraft(raw: string | null): {
  clips: EditorClip[]
  projectName: string
  resolution: ResolutionOption
  fps: number
  warning: string | null
} | null {
  if (!raw) return null
  try {
    const saved = JSON.parse(raw)
    if (!saved || !Array.isArray(saved.clips)) return null
    const resolution = RESOLUTIONS.find(option =>
      option.width === saved.resolution?.width && option.height === saved.resolution?.height,
    ) || RESOLUTIONS[0]
    const normalized = normalizeEditorClips(saved.clips, {
      idFactory: clipId,
      thumbnailUrl: api.getVideoEditorThumbnailUrl,
    })
    return {
      clips: normalized.clips,
      projectName: typeof saved.projectName === 'string' ? saved.projectName : 'my_video',
      resolution,
      fps: [24, 25, 30, 50, 60].includes(saved.fps) ? saved.fps : 30,
      warning: editorClipRecoveryMessage(normalized),
    }
  } catch {
    return null
  }
}

export function loadEditorDraft(workspace?: string | null): {
  clips: EditorClip[]
  projectName: string
  resolution: ResolutionOption
  fps: number
  warning: string | null
} {
  const fallback = { clips: [], projectName: 'my_video', resolution: RESOLUTIONS[0], fps: 30, warning: null }
  const namespacedKey = videoEditorDraftStorageKey(workspace)
  try {
    const namespaced = parseEditorDraft(window.localStorage.getItem(namespacedKey))
    if (namespaced) return namespaced
    const legacyRaw = window.localStorage.getItem(VIDEO_EDITOR_DRAFT_KEY)
    const legacy = parseEditorDraft(legacyRaw)
    if (!legacy) return fallback
    // One-shot migration: the unscoped draft belongs to the workspace that
    // first opens the editor after this change, not to every workspace.
    if (legacyRaw) {
      window.localStorage.setItem(namespacedKey, legacyRaw)
      window.localStorage.removeItem(VIDEO_EDITOR_DRAFT_KEY)
    }
    return legacy
  } catch {
    return fallback
  }
}

export function persistEditorDraft(
  clips: EditorClip[],
  projectName: string,
  resolution: ResolutionOption,
  fps: number,
  workspace?: string | null,
): boolean {
  try {
    window.localStorage.setItem(videoEditorDraftStorageKey(workspace), JSON.stringify({
      clips, projectName, resolution, fps, savedAt: new Date().toISOString(),
    }))
    return true
  } catch {
    // A full browser quota must not interrupt editing.
    return false
  }
}
