// Remaking one clip from the comic view, the way that clip was made. Every way leaves a replacement
// target for the clip, so the new video comes back to the same panel («Usar en posición N»).

import { useEffect, useState } from 'react'
import * as api from '../../api/client'
import { openSceneOutput } from '../../lib/sceneOutput'
import type { OutputMetadata } from '../../types'
import { outputNameFromEditorClip, writeVideoEditorReplacementTarget, clearVideoEditorReplacementTarget } from './replacementHandoff'
import { sceneOutput } from './shotBoardModel'

/** `creation` loads the clip's generation settings in Video creation; `scene` opens its Video 2D/3D scene;
 * `gallery` picks any other video. */
export type ClipRemake = { kind: 'creation'; outputs: string[] } | { kind: 'scene'; scene: string } | { kind: 'gallery' }

interface RemadeClip { id: string; name: string; source: string }

/** The first candidate output with reusable generation settings. */
export async function reusableMetadata(names: string[], workspace: string): Promise<OutputMetadata | null> {
  for (const name of names) {
    try {
      const metadata = await api.fetchOutputMetadata(name, workspace)
      if (metadata.params) return metadata
    } catch {
      // Try the next candidate: a copy of a generated clip keeps its settings under the original's name.
    }
  }
  return null
}

/** Open the clip's scene, or the video gallery, with the clip waiting for its replacement. */
export async function handOffClip(clip: RemadeClip, index: number, request: Exclude<ClipRemake, { kind: 'creation' }>,
  workspace: string, showVideos: () => void): Promise<void> {
  writeVideoEditorReplacementTarget({
    clipId: clip.id, clipIndex: index, originalName: clip.name,
    outputName: outputNameFromEditorClip(clip.source, clip.name), requestedAt: Date.now(),
  })
  try {
    if (request.kind === 'scene') await openSceneOutput(sceneOutput(workspace, request.scene))
    else showVideos()
  } catch (error) {
    clearVideoEditorReplacementTarget()
    throw error
  }
}

const COMIC_OPEN_KEY = 'maestro-video-editor-comic-open-v1'

/** The comic view stays open across a trip to another tab, so a remade clip lands back on its panel. */
export function useComicOpen(): [boolean, (next: (open: boolean) => boolean) => void] {
  const [open, setOpen] = useState(() => {
    try { return window.localStorage.getItem(COMIC_OPEN_KEY) === '1' } catch { return false }
  })
  useEffect(() => {
    try { window.localStorage.setItem(COMIC_OPEN_KEY, open ? '1' : '0') } catch { /* storage unavailable: the view just starts closed */ }
  }, [open])
  return [open, setOpen]
}
