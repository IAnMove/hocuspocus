import * as api from '../../api/client'
import { getMontage } from '../../api/montages'
import type { MontageEditorState } from './MontageControls'
import { editorFromMontage, resolutionFor, type MontageLayers, type MontageRef } from './montage'

/** Read a saved montage and turn it into Video Editor state (media is probed again). */
export async function loadMontageIntoEditor(workspace: string, file: string): Promise<{ state: MontageEditorState; layers: MontageLayers; ref: MontageRef }> {
  const { montage } = await getMontage(workspace, file)
  const opened = await editorFromMontage(montage, source => api.probeVideoEditorClip(source, workspace),
    source => api.probeVideoEditorAudio(source, workspace), api.getVideoEditorThumbnailUrl)
  return {
    state: { projectName: montage.name, resolution: resolutionFor(montage.width, montage.height), fps: montage.fps, clips: opened.clips, soundtrack: opened.soundtrack },
    layers: opened.layers,
    ref: { file, revision: montage.revision ?? 1, origins: opened.origins, extras: opened.extras, notes: montage.notes },
  }
}

