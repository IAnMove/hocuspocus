import * as api from '../../api/client'
import { useStore } from '../../stores/useStore'
import { useSeriesStore } from './store'
import { useSeriesNativeBatch } from './nativeBatchState'
import { allowedSeriesMethods, seriesShotMethod, seriesTakeStage } from './productionMethods'
import { seriesShotReferences } from './shotReferences'
import { prepareCharacterCutout } from './characterCutout'
import { prepareNativeDraft } from './nativeDraftScene'
import { presentSceneDocument } from '../sceneFx/handoff'
import { openAgentSeriesSection, requestAgentSceneWorkflow } from '../../lib/uiBus'
import type { SeriesEpisode, SeriesProject } from './types'

export function nativeDraftCandidates(series: SeriesProject, episode: SeriesEpisode) {
  return allowedSeriesMethods(series).includes('animation_2d') ? episode.shots.filter(shot =>
    seriesShotMethod(series, shot) === 'animation_2d' && seriesTakeStage(shot) === 'missing'
    && !shot.attempts.some(attempt => ['queued', 'running', 'cancelling'].includes(attempt.status))) : []
}

function source(workspace: string, seriesId: string, episodeId: string) {
  const state = useSeriesStore.getState()
  if (useStore.getState().activeWorkspace !== workspace || state.workspace !== workspace
    || state.activeSeriesId !== seriesId || state.activeEpisodeId !== episodeId) throw new Error('Return to the source episode before continuing this batch.')
  const series = state.library.seriesById[seriesId], episode = series?.episodesById[episodeId]
  if (!episode) throw new Error('The source episode is unavailable')
  return { series, episode }
}

async function cleanShotCharacters(workspace: string, seriesId: string, episodeId: string, shotId: string) {
  const { series, episode } = source(workspace, seriesId, episodeId)
  const shot = episode.shots.find(item => item.id === shotId)!
  const refs = seriesShotReferences(series, episode, shot)
  if (!refs.ready) throw new Error('Review the character/location links in the episode status before generating this shot.')
  for (const person of refs.people) {
    useSeriesNativeBatch.setState({ phase: 'cleaning' })
    const current = source(workspace, seriesId, episodeId).series
    const result = await prepareCharacterCutout(workspace, current, person.asset!)
    useSeriesStore.getState().acceptAssetImport(workspace, result)
  }
}

async function renderNativeShot(workspace: string, seriesId: string, episodeId: string, shotId: string) {
  await cleanShotCharacters(workspace, seriesId, episodeId, shotId)
  const { series, episode } = source(workspace, seriesId, episodeId)
  const shot = episode.shots.find(item => item.id === shotId)!
  useSeriesNativeBatch.setState({ phase: 'voices' })
  const prepared = await prepareNativeDraft(workspace, series, episode, shot, await api.fetchCharacterKitLibrary(workspace))
  source(workspace, seriesId, episodeId)
  useSeriesStore.getState().updateEpisode(episodeId, current => ({ ...current,
    shots: current.shots.map(item => item.id === shotId ? { ...item, durationSeconds: prepared.shot.durationSeconds } : item) }))
  await useSeriesStore.getState().saveNow()
  sessionStorage.setItem(`hocuspocus:series-scene:${workspace}:${seriesId}:${episodeId}:${shotId}`, JSON.stringify(prepared.scene))
  useSeriesNativeBatch.setState({ phase: 'rendering' })
  useStore.getState().setMediaFilter('scene3d')
  await presentSceneDocument('2d', prepared.scene, () => useStore.getState().activeWorkspace === workspace)
  // The same editor performs both persistence and rendering; no second compositor.
  const scene = await requestAgentSceneWorkflow({ type: 'save_3d_scene', sceneName: prepared.scene.name || '' })
  const video = await requestAgentSceneWorkflow({ type: 'export_3d_scene', sceneName: prepared.scene.name || '' })
  const filename = video.outputNames?.[0]
  if (!filename) throw new Error('The editor did not return a finished video')
  source(workspace, seriesId, episodeId)
  const response = await fetch(api.getFileUrl(filename, workspace))
  if (!response.ok) throw new Error('The generated video is unavailable')
  const upload = await api.uploadImage(new File([await response.blob()], filename, { type: 'video/mp4' }))
  const result = await api.importSeriesAsset(workspace, seriesId, { uploadPath: upload.path, name: filename,
    ownerType: 'shot', ownerId: shotId, kind: 'video', asTake: true,
    metadata: { productionMethod: 'animation_2d', sceneFilename: scene.outputNames?.[0], automaticDraft: true } })
  useSeriesStore.getState().acceptAssetImport(workspace, result)
}

export async function generateNativeDrafts(workspace: string, seriesId: string, episodeId: string) {
  if (useSeriesNativeBatch.getState().running) return
  useSeriesNativeBatch.setState({ running: true, stopping: false, workspace, seriesId, episodeId, completed: 0, total: 0, order: 0, phase: 'preparing', error: '' })
  try {
    await useSeriesStore.getState().saveNow()
    const { series, episode } = source(workspace, seriesId, episodeId)
    const shots = nativeDraftCandidates(series, episode)
    useSeriesNativeBatch.setState({ total: shots.length })
    for (const shot of shots) {
      if (useSeriesNativeBatch.getState().stopping) break
      source(workspace, seriesId, episodeId)
      useSeriesNativeBatch.setState({ order: shot.order })
      await renderNativeShot(workspace, seriesId, episodeId, shot.id)
      useSeriesNativeBatch.setState(state => ({ completed: state.completed + 1 }))
    }
  } catch (reason) { useSeriesNativeBatch.setState({ error: (reason as Error).message }) }
  finally {
    useSeriesNativeBatch.setState({ running: false })
    if (useStore.getState().activeWorkspace === workspace) {
      useStore.getState().setMediaFilter('series')
      // Series Lab mounts on return and then receives the destination.
      setTimeout(() => openAgentSeriesSection('review'), 250)
    }
  }
}
