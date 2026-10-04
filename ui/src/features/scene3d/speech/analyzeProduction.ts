import { analyzeSceneSpeechDetailed } from '../../../api/scene3dSpeech'
import { analysisDriver } from './analysis'
import { voiceWav } from './audio'
import { amplitudeCues, parseMouthCues } from './track'
import type { SpeechProductionInput } from './production'
import type { SpeechClip } from './types'

/** One continuous source clock for every speaker in this shot. */
export async function analyzeProductionTrack(input: SpeechProductionInput, buffer: AudioBuffer,
  phonetic: boolean, signal?: AbortSignal): Promise<Pick<SpeechClip, 'cues' | 'driver' | 'analysisEngine' | 'language' | 'analysisFallback'>> {
  const analysisEngine = input.analysis?.analysisEngine ?? 'auto', language = input.analysis?.language
  const settings = { analysisEngine, language, analysisFallback: null }
  if (!phonetic) return { ...settings, cues: amplitudeCues(buffer, input.offset, input.duration), driver: 'amplitude' }
  const dialogue = input.analysis?.text || input.lines?.map(line => line.text).join(' ')
  const result = await analyzeSceneSpeechDetailed(await voiceWav(buffer, input.offset, input.duration), {
    signal, dialogue, engine: analysisEngine, language, isolateVocals: input.analysis?.isolateVocals,
  })
  return { ...settings, analysisFallback: result.fallbackReason ?? null,
    cues: parseMouthCues(result).map(c => ({ ...c, start: c.start + input.offset, end: c.end + input.offset })),
    driver: analysisDriver(result, input.analysis?.isolateVocals) }
}
