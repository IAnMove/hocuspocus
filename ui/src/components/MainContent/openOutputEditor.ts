import { fetchSeriesLibrary, loadComicProject } from '../../api/client'
import { normalizeComicProject } from '../../features/comics/model'
import { resolveComicSource } from '../../features/comics/provenance'
import { useComicStore } from '../../features/comics/store'
import { openSceneOutput } from '../../lib/sceneOutput'
import { useStore } from '../../stores/useStore'
import type { OutputFile } from '../../types'

/** Saved scenes and comics are documents: "opening" one loads it into its
 *  editor. Rejects with the reason when the document cannot be loaded. */
export async function openOutputInEditor(file: OutputFile): Promise<void> {
  if (file.type === 'scene') {
    await openSceneOutput(file)
    return
  }
  if (file.type !== 'comic') return
  const project = normalizeComicProject(await loadComicProject(file.name))
  if (project.provenance) {
    const library = await fetchSeriesLibrary(project.provenance.workspaceId)
    resolveComicSource(project, library, project.provenance.workspaceId)
  }
  useComicStore.getState().setProject(project, file.name)
  useStore.getState().setMediaFilter('comics')
}
