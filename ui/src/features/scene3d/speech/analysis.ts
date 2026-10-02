import type { SpeechAnalysisResponse } from '../../../api/scene3dSpeech'
import { SPEECH_ENGINES, type Scene3DSpeech, type SpeechAnalysisSettings, type SpeechEngine } from './types'

export function speechAnalysisSettings(data: Record<string, unknown>): SpeechAnalysisSettings {
  if (data.analysisEngine !== undefined && !SPEECH_ENGINES.includes(data.analysisEngine as SpeechEngine)) throw new Error('Invalid lip-sync engine.')
  if (data.analysisFallback !== undefined && data.analysisFallback !== null && data.analysisFallback !== 'phoneme_not_installed') throw new Error('Invalid lip-sync fallback.')
  if (data.text !== undefined && (typeof data.text !== 'string' || data.text.length > 4000 || data.text.includes('\0'))) throw new Error('Invalid dialogue text.')
  if (data.language !== undefined && (typeof data.language !== 'string' || data.language.length > 16)) throw new Error('Invalid dialogue language.')
  return { ...(data.analysisEngine !== undefined ? { analysisEngine: data.analysisEngine as SpeechEngine } : {}),
    ...(data.analysisFallback !== undefined ? { analysisFallback: data.analysisFallback as SpeechAnalysisSettings['analysisFallback'] } : {}),
    ...(data.text !== undefined ? { text: data.text as string } : {}), ...(data.language !== undefined ? { language: data.language as string } : {}) }
}

export function analysisDriver(result: SpeechAnalysisResponse, isolateVocals = false): Scene3DSpeech['driver'] {
  if (result.driver) return result.driver
  const engine = result.engine ?? (result.recognizer === 'wav2vec2-phoneme' ? 'phoneme' : 'rhubarb')
  return (result.analysisSource ? result.analysisSource === 'isolated-vocals' : isolateVocals) ? `${engine}-vocals` : engine
}
