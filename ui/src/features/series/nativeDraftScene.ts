import * as api from '../../api/client'
import { generateSceneSpeechClip } from '../../lib/sceneSpeech'
import type { CharacterKitLibrary } from '../../lib/characterKit'
import type { CharacterKitReviewPolicy } from '../../lib/characterKitReview'
import { decodeVoice } from '../scene3d/speech/audio'
import { buildSeriesShotScene } from './shotScene'
import type { SeriesEpisode, SeriesProject, SeriesShot } from './types'
import type { Scene, SceneLayer } from '../../types'
import { applySeriesLipSync } from './nativeLipSync'

export async function submitSeriesSpeech(params: Record<string, unknown>, pendingKey: string) {
  const pending = localStorage.getItem(pendingKey)
  if (pending) {
    const job = await api.fetchJobStatus(pending)
    if (!['failed', 'cancelled'].includes(job.status)) return { job_id: pending, status: job.status }
    localStorage.removeItem(pendingKey)
  }
  const job = await api.submitGeneration(params)
  localStorage.setItem(pendingKey, job.job_id)
  return job
}

async function dialogueAudio(workspace: string, shot: SeriesShot, series: SeriesProject, kits: CharacterKitLibrary) {
  let cursor = .25
  const audioTracks: NonNullable<Scene['audioTracks']> = []
  const dialogueBeats: NonNullable<Scene['dialogueBeats']> = []
  for (const beat of shot.dialogueBeats) {
    const character = series.characters.find(item => item.id === beat.characterId)
    const ref = character?.voiceProfile?.characterKitRef
    const voice = ref?.workspace === workspace ? kits.kits[ref.id]?.voice : undefined
    if (!voice) throw new Error(`Configure the saved voice for ${character?.name || beat.characterId} before generating this shot.`)
    const key = `hocuspocus:series-speech:${JSON.stringify([workspace, series.id, shot.id, beat.id, beat.text, voice])}`
    let filename = localStorage.getItem(key)
    if (!filename) {
      const pendingKey = `${key}:job`
      const clip = await generateSceneSpeechClip({ workspace, prompt: beat.text, model: voice.model, voice,
        durationSeconds: shot.durationSeconds }, { fetchJobStatus: api.fetchJobStatus, cancelJob: api.cancelJob,
        submitGeneration: params => submitSeriesSpeech(params, pendingKey) })
      filename = clip.filename; localStorage.setItem(key, filename)
      localStorage.removeItem(pendingKey)
    }
    const buffer = await decodeVoice(api.getFileUrl(filename, workspace))
    audioTracks.push({ id: beat.id, filename, name: character!.name, kind: 'speech', startTime: cursor, volume: 1, prompt: beat.text, model: voice.model })
    dialogueBeats.push({ id: beat.id, text: beat.text, start: cursor, end: cursor + buffer.duration,
      audioTrackId: beat.id, mouthLayerIds: [], confidence: 'aligned-audio' })
    cursor += buffer.duration + .2
  }
  return { audioTracks, dialogueBeats, duration: Math.max(shot.durationSeconds, cursor + .15) }
}

/** Limited-animation blocking stays ordinary, editable Scene Animator keyframes. */
export function animateSeriesDraft(scene: Scene, shot: SeriesShot): Scene {
  const close = /close|primer/i.test(shot.framing)
  const wide = /wide|general/i.test(shot.framing)
  const cast = scene.layers.filter(layer => shot.visibleCharacterIds.includes(layer.id))
  const layers = scene.layers.map(layer => {
    if (!cast.includes(layer)) return layer
    const scale = close && cast.length < 3 ? 1.35 : wide ? .7 : .95
    const transform = { ...layer.transform, scale, y: close ? 92 : 68, rotation: 0 }
    const dialogue = shot.dialogueBeats.filter(beat => beat.characterId === layer.id)
    const windows = scene.dialogueBeats?.filter(beat => dialogue.some(line => line.id === beat.id)) || []
    const times = Array.from({ length: Math.ceil(scene.duration * 4) + 1 }, (_, index) => Math.min(scene.duration, index / 4))
    const keyframes = times.map((time, index) => {
      const talking = windows.some(beat => time >= beat.start && time <= beat.end)
      return { ...transform, id: `${layer.id}-${index}`, time, curve: 'hold' as const,
        y: transform.y + (talking ? Math.sin(index * 1.6) * .65 : Math.sin(time * 1.8) * .15),
        rotation: talking ? Math.sin(index * 1.1) * .7 : 0 }
    })
    return { ...layer, transform, animation: { ...layer.animation, start: transform, end: transform, keyframes } }
  })
  if (/push|pan|zoom|travelling/i.test(shot.camera)) {
    const start = { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 }
    const camera: SceneLayer = { id: 'series-camera', name: shot.camera, type: 'camera', source: '', visible: true, z: 100,
      transform: start, animation: { start, end: { ...start, scale: 1.08 }, duration: scene.duration, curve: 'ease' } }
    layers.push(camera)
  }
  return { ...scene, layers }
}

export async function prepareNativeDraft(workspace: string, series: SeriesProject, episode: SeriesEpisode,
  shot: SeriesShot, kits: CharacterKitLibrary, bodySources: Record<string, string> = {}, policy: CharacterKitReviewPolicy = 'approved') {
  const speech = await dialogueAudio(workspace, shot, series, kits)
  const durationSeconds = Math.ceil(speech.duration * 30) / 30
  if (durationSeconds > 180) throw new Error('Split this shot before rendering: its dialogue exceeds three minutes.')
  const currentShot = { ...shot, durationSeconds }
  const prepared = buildSeriesShotScene(workspace, series, episode, currentShot)
  if (prepared.dimension !== '2d') throw new Error('Automatic drafts currently require a 2D shot.')
  const scene = animateSeriesDraft({ ...prepared.document, audioTracks: speech.audioTracks,
    dialogueBeats: speech.dialogueBeats }, currentShot)
  return { shot: currentShot, scene: applySeriesLipSync(scene, workspace, series, currentShot, kits, bodySources, policy) }
}
