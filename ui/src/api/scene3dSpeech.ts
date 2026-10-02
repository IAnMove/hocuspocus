import { BASE } from './http'
import { parseMouthCues } from '../features/scene3d/speech/track'
import type { Scene3DSpeech, SpeechEngine } from '../features/scene3d/speech/types'

export type SpeechAnalysisResponse = {
  mouthCues: { start: number; end: number; value: string }[]
  recognizer: 'phonetic' | 'pocketSphinx' | 'wav2vec2-phoneme'; duration: number
  engine?: 'phoneme' | 'rhubarb'; requestedEngine?: SpeechEngine; driver?: Scene3DSpeech['driver']
  analysisSource?: 'original' | 'isolated-vocals'; fallbackReason?: 'phoneme_not_installed' | null
  quality?: { low_confidence_phonemes: number; review_required: boolean } | null
}
export type SpeechAnalysisOptions = { signal?: AbortSignal; isolateVocals?: boolean; dialogue?: string; language?: string; engine?: SpeechEngine }
export async function analyzeSceneSpeech(wav: ArrayBuffer, signal?: AbortSignal, isolateVocals = false) {
  const data = await analyzeSceneSpeechDetailed(wav, { signal, isolateVocals })
  return parseMouthCues(data)
}

export async function analyzeSceneSpeechDetailed(wav: ArrayBuffer,
  options: SpeechAnalysisOptions = {}) {
  const { signal, isolateVocals = false, dialogue, language = '', engine = 'auto' } = options
  const withScript = dialogue !== undefined || !!language || engine !== 'auto'
  let body: ArrayBuffer | string = wav
  if (withScript) {
    let binary = ''
    const bytes = new Uint8Array(wav)
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
    body = JSON.stringify({ wavBase64: btoa(binary), dialogue: dialogue ?? '', language, engine })
  }
  const response = await fetch(`${BASE}/api/v1/character-kits/speech/analyze${isolateVocals ? '?isolate_vocals=true' : ''}`, {
    method: 'POST', headers: { 'Content-Type': withScript ? 'application/json' : 'audio/wav' }, body, signal,
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(typeof error?.detail === 'string' ? error.detail : 'Local speech analysis failed.')
  }
  const data: SpeechAnalysisResponse = await response.json()
  parseMouthCues(data)
  return data
}

export async function setupSpeechPhonemes(install = false, signal?: AbortSignal) {
  const response = await fetch(`${BASE}/api/v1/character-kits/speech/phonemes/setup`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, signal,
    body: JSON.stringify({ version: 1, input: { install } }),
  })
  const receipt = await response.json()
  if (!response.ok || receipt.status !== 'completed') throw new Error(receipt.detail?.message || 'Phoneme engine setup failed.')
  return receipt.result as { installed: boolean; dependencies_available: boolean; download_bytes: number; device: string }
}
