import { analyzeSceneSpeechDetailed } from '../../api/scene3dSpeech'
import { getFileUrl } from '../../api/client'
import { decodeVoice, voiceWav } from '../scene3d/speech/audio'
import { parseMouthCues } from '../scene3d/speech/track'
import { rebuildCutoutDialogueLayers } from '../../lib/cutoutDialogue'
import type { Scene } from '../../types'

export const nativeSpeechAnalysisServices = { analyze: analyzeSceneSpeechDetailed, decode: decodeVoice, wav: voiceWav }

/** Analyze each isolated actor recording, never the music/mixed soundtrack. */
export async function analyzeNativeSpeech(scene: Scene, workspace: string, language: string,
  services = nativeSpeechAnalysisServices): Promise<Scene> {
  const beats = []
  for (const beat of scene.dialogueBeats ?? []) {
    if (!beat.mouthLayerIds.length) { beats.push(beat); continue }
    const track = scene.audioTracks?.find(item => item.id === beat.audioTrackId)
    if (!track || track.prompt !== beat.text) throw new Error('The dialogue recording changed. Prepare its voice again.')
    const buffer = await services.decode(getFileUrl(track.filename, workspace))
    const offset = Math.max(0, beat.start - track.startTime)
    const duration = Math.min(beat.end - beat.start, buffer.duration - offset)
    if (duration <= 0 || beat.end - beat.start > duration + .05) throw new Error('The dialogue extends beyond its recording.')
    const analyzed = await services.analyze(await services.wav(buffer, offset, duration), { dialogue: beat.text, language })
    beats.push({ ...beat, confidence: 'aligned-audio' as const, lipSync: { version: 1 as const,
      driver: analyzed.recognizer, text: beat.text, audioTrackId: track.id, filename: track.filename,
      offset, duration, cues: parseMouthCues(analyzed) } })
  }
  return { ...scene, dialogueBeats: beats,
    layers: rebuildCutoutDialogueLayers(scene.layers, beats, scene.fps || 30, scene.duration) }
}
