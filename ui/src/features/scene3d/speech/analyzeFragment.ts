import { analyzeSceneSpeechDetailed } from '../../../api/scene3dSpeech'
import { analysisDriver } from './analysis'
import { voiceWav } from './audio'
import { analysisWindow, mapFragmentCues, replaceCueInterval } from './cueEdit'
import { parseMouthCues } from './track'
import type { Scene3DSpeech } from './types'

export async function analyzeSpeechFragment(speech: Scene3DSpeech, buffer: AudioBuffer,
  from: number, to: number, signal: AbortSignal, isolateVocals: boolean): Promise<Scene3DSpeech> {
  const fragment = analysisWindow(from, to, buffer.duration)
  const turnEnd = Math.min(buffer.duration, speech.offset + (speech.end === undefined ? buffer.duration - speech.offset : speech.end - speech.start))
  // A partial selection cannot be forced against the entire intervention text.
  const wholeTurn = Math.abs(fragment.start - speech.offset) < .001 && Math.abs(fragment.start + fragment.duration - turnEnd) < .001
  const result = await analyzeSceneSpeechDetailed(await voiceWav(buffer, fragment.start, fragment.duration), {
    signal, isolateVocals, engine: speech.analysisEngine ?? 'auto', dialogue: wholeTurn ? speech.text || undefined : undefined, language: speech.language,
  })
  const mapped = mapFragmentCues(parseMouthCues(result), fragment.start)
  return { ...speech, cues: replaceCueInterval(speech.cues, fragment.start, fragment.start + fragment.duration, mapped),
    driver: analysisDriver(result, isolateVocals), analysisFallback: result.fallbackReason ?? null }
}
