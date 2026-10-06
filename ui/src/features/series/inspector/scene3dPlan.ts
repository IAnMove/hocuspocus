import { openShotScene3D, saveShotScene3D } from '../../../api/seriesShotInspector'
import { useStore } from '../../../stores/useStore'
import { presentSceneDocument } from '../../sceneFx/handoff'
import { useSeriesStore } from '../store'
import { returnToShot, setShotEditSession, type ShotEditSession } from '../shotEditSession'
import type { SeriesEpisode, SeriesProject, SeriesShot } from '../types'

/**
 * A 3D shot's plan (its template or saved scene with its objects) in the Video 3D editor, and back: saving there
 * stores the edited scene and writes it to the shot's scene3d through the shot edit, which resets its approvals.
 */
export async function openShotScene3DPlan(workspace: string, series: SeriesProject, episode: SeriesEpisode, shot: SeriesShot) {
  await useSeriesStore.getState().saveNow()
  const opened = await openShotScene3D(workspace, series.id, episode.id, shot.id)
  const { parseScene3DDocument } = await import('../../scene3d/document')
  const document = parseScene3DDocument(opened.document)
  if (!document) throw new Error('The 3D scene of this shot could not be read by the Video 3D editor')
  const current = () => useStore.getState().activeWorkspace === workspace
  if (!current()) throw new Error('The workspace changed while opening the scene')
  setShotEditSession({
    workspace, seriesId: series.id, episodeId: episode.id, shotId: shot.id, order: shot.order, episodeTitle: episode.title,
    sceneFilename: opened.source.scene || '', sceneName: String((document as { name?: unknown }).name || ''), dimension: '3d',
    productionMethod: 'animation_3d', openedAt: Date.now(), target: 'plan',
  })
  const state = useStore.getState()
  state.setSettingsOpen(false); state.setDashboardOpen(false)
  state.setMediaFilter('world3d')
  await presentSceneDocument('3d', document, current)
}

/** The document open in the Video 3D editor right now (the editor publishes it while it is mounted). */
export function openWorld3DDocument(): unknown {
  return (window as Window & { __world3dDocument?: unknown }).__world3dDocument
}

/** Series Lab's copy of the shot's episode, loaded again when the page was reloaded inside the editor. */
async function openShotEpisode(session: ShotEditSession) {
  const store = useSeriesStore.getState()
  if (store.workspace !== session.workspace || !store.hydrated) await store.loadWorkspace(session.workspace)
  if (useSeriesStore.getState().activeSeriesId !== session.seriesId) await useSeriesStore.getState().openSeries(session.seriesId)
  useSeriesStore.getState().openEpisode(session.episodeId)
}

/** Save what the Video 3D editor shows to the shot it was opened from, then go back to that shot. */
export async function saveScene3DPlan(session: ShotEditSession, document: unknown = openWorld3DDocument()) {
  if (!document) throw new Error('Open the Video 3D editor with the shot first')
  if (useStore.getState().activeWorkspace !== session.workspace) throw new Error('Return to the workspace of this shot first')
  await openShotEpisode(session)
  const saved = await saveShotScene3D(session.workspace, session.seriesId, session.episodeId, session.shotId, document)
  await useSeriesStore.getState().editShot(session.episodeId, { shot: session.shotId, changes: { scene3d: saved.scene3d } })
  setShotEditSession(null)
  returnToShot(session)
  return saved
}
