import { create } from 'zustand'
import * as api from '../../api/client'
import type { ApiOutput } from '../../api/client'
import { ensureUploadsPath } from '../../lib/labsImagePick'
import { safeStorageGet, safeStorageRemove, safeStorageSet } from '../../lib/safeStorage'
import { openAgentSeriesSection, requestAgentSceneWorkflow } from '../../lib/uiBus'
import { useStore } from '../../stores/useStore'
import { presentSceneDocument } from '../sceneFx/handoff'
import { useSeriesStore } from './store'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'
import { latestTakeMedia } from './reviewModel'

/**
 * A shot opened in the Video 2D / Video 3D editor from Series Lab, kept for the round trip: the editor's export goes
 * back to that shot as a new take (which the staged review treats as a preview to look at again).
 */
export interface ShotEditSession {
  workspace: string
  seriesId: string
  episodeId: string
  shotId: string
  order: number
  episodeTitle: string
  sceneFilename: string
  sceneName: string
  dimension: '2d' | '3d'
  productionMethod: string
  openedAt: number
}

const KEY = 'hocuspocus:series-shot-edit'

function restored(): ShotEditSession | null {
  try {
    const value = JSON.parse(safeStorageGet('session', KEY) || 'null')
    return value && typeof value === 'object' && typeof value.shotId === 'string' ? value as ShotEditSession : null
  } catch { return null }
}

export const useShotEditSession = create<{ session: ShotEditSession | null; focusShotId: string }>(() => ({ session: restored(), focusShotId: '' }))

export function setShotEditSession(session: ShotEditSession | null) {
  if (session) safeStorageSet('session', KEY, JSON.stringify(session)); else safeStorageRemove('session', KEY)
  useShotEditSession.setState({ session })
}

/** Open EXACTLY the scene the shot's latest take was rendered from, in its own editor. */
export async function openShotInEditor(workspace: string, series: SeriesProject, episode: SeriesEpisode, shot: SeriesShot) {
  const sceneFilename = latestTakeMedia(series, shot)?.sceneFilename
  if (!sceneFilename) throw new Error('This take has no editable scene')
  const response = await fetch(api.getFileUrl(sceneFilename, workspace))
  if (!response.ok) throw new Error('Could not load the scene of this take')
  const raw = await response.text()
  const world = sceneFilename.endsWith('.world3d.scene.json')
  const document = world
    ? (await import('../scene3d/document')).parseScene3DDocument(JSON.parse(raw))
    : (await import('../../lib/sceneFile')).parseSceneFile(raw)
  if (!document) throw new Error('Could not load the scene of this take')
  const current = () => useStore.getState().activeWorkspace === workspace
  if (!current()) throw new Error('The workspace changed while opening the scene')
  setShotEditSession({
    workspace, seriesId: series.id, episodeId: episode.id, shotId: shot.id, order: shot.order, episodeTitle: episode.title,
    sceneFilename, sceneName: String((document as { name?: unknown }).name || ''), dimension: world ? '3d' : '2d',
    productionMethod: shot.productionMethod || (world ? 'animation_3d' : 'animation_2d'), openedAt: Date.now(),
  })
  const state = useStore.getState()
  state.setSettingsOpen(false); state.setDashboardOpen(false)
  state.setMediaFilter(world ? 'world3d' : 'scene3d')
  await presentSceneDocument(world ? '3d' : '2d', document, current)
}

async function importTake(session: ShotEditSession, uploadPath: string, name: string, sceneFilename: string) {
  if (useStore.getState().activeWorkspace !== session.workspace) throw new Error('Return to the workspace of this shot first')
  const result = await api.importSeriesAsset(session.workspace, session.seriesId, {
    uploadPath, name, ownerType: 'shot', ownerId: session.shotId, kind: 'video', asTake: true,
    metadata: { productionMethod: session.productionMethod, sceneFilename, editedInEditor: true },
  })
  useSeriesStore.getState().acceptAssetImport(session.workspace, result)
  setShotEditSession(null)
}

/** Save and export the open 2D scene (as the server-side batch does), then make the video the shot's new take. */
export async function exportEditorTake(session: ShotEditSession) {
  const saved = await requestAgentSceneWorkflow({ type: 'save_3d_scene', sceneName: session.sceneName })
  const video = await requestAgentSceneWorkflow({ type: 'export_3d_scene', sceneName: session.sceneName })
  const filename = video.outputNames?.[0]
  if (!filename) throw new Error('The editor did not return a finished video')
  const response = await fetch(api.getFileUrl(filename, session.workspace))
  if (!response.ok) throw new Error('The exported video is unavailable')
  const upload = await api.uploadImage(new File([await response.blob()], filename, { type: 'video/mp4' }))
  await importTake(session, upload.path, filename, saved.outputNames?.[0] || session.sceneFilename)
}

/** A video exported from the editor (or anywhere) after the shot was opened, chosen by the user. */
export async function importExportAsTake(session: ShotEditSession, item: ApiOutput) {
  const uploaded = await ensureUploadsPath(item)
  await importTake(session, uploaded.path, item.name, session.sceneFilename)
}

/** Videos created in the workspace since the shot was opened, newest first. */
export async function recentExports(session: ShotEditSession, limit = 6): Promise<ApiOutput[]> {
  const { outputs } = await api.fetchOutputs(40, 0, { workspace: session.workspace, mediaType: 'video' })
  const made = (item: ApiOutput) => { const value = item.completed_at || item.created_at || 0; return value < 1e12 ? value * 1000 : value }
  return outputs.filter(item => made(item) >= session.openedAt - 1000).sort((a, b) => made(b) - made(a)).slice(0, limit)
}

/** Back to Series Lab, on the review tab with the edited shot in view. */
export async function returnToShot(session: ShotEditSession) {
  const current = () => useStore.getState().activeWorkspace === session.workspace && useSeriesStore.getState().workspace === session.workspace
  if (useStore.getState().activeWorkspace !== session.workspace) throw new Error('Return to the workspace of this shot first')
  await useSeriesStore.getState().loadWorkspace(session.workspace)
  if (!current()) throw new Error('The workspace changed while returning to the shot')
  await useSeriesStore.getState().openSeries(session.seriesId)
  const state = useSeriesStore.getState()
  const episode = state.library.seriesById[session.seriesId]?.episodesById[session.episodeId]
  if (!current() || state.activeSeriesId !== session.seriesId || !episode?.shots.some(shot => shot.id === session.shotId)) {
    throw new Error(state.error || 'The edited shot is no longer available')
  }
  state.openEpisode(session.episodeId)
  useShotEditSession.setState({ focusShotId: session.shotId })
  openAgentSeriesSection('approval')
  useStore.getState().setMediaFilter('series')
}
