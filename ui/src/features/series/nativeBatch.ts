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
import type { CharacterKitLibrary } from '../../lib/characterKit'
import { applySeriesLipSync, seriesLipSyncFingerprint, seriesLipSyncIssues, seriesSpeakerKit } from './nativeLipSync'
import { latestNativeTake, lipSyncUpdatePlan } from './nativeTake'
import { seriesAssetUrl } from './referenceImages'
import i18n from '../../i18n'

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

async function cleanShotCharacters(workspace: string, seriesId: string, episodeId: string, shotId: string, kits: CharacterKitLibrary) {
  const { series, episode } = source(workspace, seriesId, episodeId)
  const shot = episode.shots.find(item => item.id === shotId)!
  const refs = seriesShotReferences(series, episode, shot)
  if (!refs.ready) throw new Error('Review the character/location links in the episode status before generating this shot.')
  const bodySources: Record<string, string> = {}
  for (const person of refs.people) {
    useSeriesNativeBatch.setState({ phase: 'cleaning' })
    const current = source(workspace, seriesId, episodeId).series
    const kit = shot.dialogueBeats.some(beat => beat.characterId === person.id) ? seriesSpeakerKit(workspace, current, person.id, kits) : undefined
    if (kit?.base?.alphaStatus === 'transparent') { bodySources[person.id] = kit.base.source; continue }
    const variant = kit?.base ? { sourceKey: JSON.stringify([kit.id, kit.base.id, kit.base.source]),
      sourceUrl: /^(https?:|\/)/.test(kit.base.source) ? kit.base.source : api.getFileUrl(kit.base.source, workspace) } : undefined
    const result = await prepareCharacterCutout(workspace, current, person.asset!, variant)
    useSeriesStore.getState().acceptAssetImport(workspace, result)
    bodySources[person.id] = seriesAssetUrl(result.asset)
  }
  return bodySources
}

async function renderNativeShot(workspace: string, seriesId: string, episodeId: string, shotId: string, updateLipSync: boolean) {
  const kits = await api.fetchCharacterKitLibrary(workspace)
  const before = source(workspace, seriesId, episodeId)
  assertLipSyncReady(workspace, before.series, [before.episode.shots.find(item => item.id === shotId)!], kits)
  const bodySources = await cleanShotCharacters(workspace, seriesId, episodeId, shotId, kits)
  const { series, episode } = source(workspace, seriesId, episodeId)
  const shot = episode.shots.find(item => item.id === shotId)!
  useSeriesNativeBatch.setState({ phase: 'voices' })
  const prepared = updateLipSync
    ? await updateSavedLipSync(workspace, series, episode, shot, kits, bodySources)
    : await prepareNativeDraft(workspace, series, episode, shot, kits, bodySources)
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
    metadata: { productionMethod: 'animation_2d', sceneFilename: scene.outputNames?.[0], automaticDraft: true,
      lipSyncFingerprint: seriesLipSyncFingerprint(workspace, series, prepared.shot, kits) } })
  useSeriesStore.getState().acceptAssetImport(workspace, result)
}

function assertLipSyncReady(workspace: string, series: SeriesProject, shots: SeriesEpisode['shots'], kits: CharacterKitLibrary) {
  const issues = seriesLipSyncIssues(workspace, series, shots, kits)
  if (issues.length) throw new Error(issues.map(issue => `${issue.name}: ${i18n.t(`seriesLab:native.lipsyncIssues.${issue.reason}`)}`).join('\n'))
}

async function updateSavedLipSync(workspace: string, series: SeriesProject, episode: SeriesEpisode,
  shot: SeriesEpisode['shots'][number], kits: CharacterKitLibrary, bodySources: Record<string, string>) {
  const take = latestNativeTake(series, shot)
  if (!take) throw new Error(i18n.t('seriesLab:native.sceneUnavailable'))
  const response = await fetch(api.getFileUrl(take.metadata.sceneFilename as string, workspace))
  if (!response.ok) throw new Error(i18n.t('seriesLab:native.sceneUnavailable'))
  const { parseSceneFile } = await import('../../lib/sceneFile')
  const scene = parseSceneFile(await response.text())
  const controls = scene.narrative?.controls
  if (controls?.seriesId !== series.id || controls?.episodeId !== episode.id || controls?.shotId !== shot.id) {
    throw new Error(i18n.t('seriesLab:native.sceneUnavailable'))
  }
  return { shot: { ...shot, durationSeconds: scene.duration }, scene: applySeriesLipSync(scene, workspace, series, shot, kits, bodySources) }
}

export async function generateNativeDrafts(workspace: string, seriesId: string, episodeId: string, updateLipSync = false) {
  if (useSeriesNativeBatch.getState().running) return
  useSeriesNativeBatch.setState({ running: true, stopping: false, workspace, seriesId, episodeId, completed: 0, total: 0, order: 0, phase: 'preparing', error: '' })
  try {
    await useSeriesStore.getState().saveNow()
    const { series, episode } = source(workspace, seriesId, episodeId)
    const kits = await api.fetchCharacterKitLibrary(workspace)
    const shots = updateLipSync ? lipSyncUpdatePlan(workspace, series, episode, kits).ready : nativeDraftCandidates(series, episode)
    assertLipSyncReady(workspace, series, shots, kits)
    useSeriesNativeBatch.setState({ total: shots.length })
    for (const shot of shots) {
      if (useSeriesNativeBatch.getState().stopping) break
      source(workspace, seriesId, episodeId)
      useSeriesNativeBatch.setState({ order: shot.order })
      await renderNativeShot(workspace, seriesId, episodeId, shot.id, updateLipSync)
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
