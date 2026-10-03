import type { Scene3DDocument } from '../types'
import type { Scene3DSpeech, SpeechClip } from './types'

export function speechClips(speech: Scene3DSpeech): SpeechClip[] {
  return speech.clips ?? [{ id: 'voice', audio: speech.audio, cues: speech.cues, driver: speech.driver,
    start: speech.start, offset: speech.offset, gain: speech.gain, end: speech.end, audible: speech.audible,
    analysisEngine: speech.analysisEngine, analysisFallback: speech.analysisFallback, language: speech.language, text: speech.text }]
}
export function sceneVoiceTracks(document: Scene3DDocument) {
  return [
    ...(document.soundtrack ?? []).map(track => ({ ...track, key: 'soundtrack/' + track.id })),
    ...document.slots.flatMap(slot => slot.speech?.enabled ? speechClips(slot.speech)
      .filter(clip => clip.audio && clip.audible !== false).map(clip => ({ ...clip, key: slot.id + '/' + clip.id })) : []),
  ].filter(track => track.audio)
}
export function speechEnd(speech: Scene3DSpeech) {
  return Math.max(0, ...speechClips(speech).map(clip => clip.end ?? clip.start + (clip.cues.at(-1)?.end ?? 0) - clip.offset))
}
