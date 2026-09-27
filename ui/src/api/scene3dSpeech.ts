import { BASE } from './http'
import { parseMouthCues } from '../features/scene3d/speech/track'

export type SpeechAnalysisResponse = { mouthCues: { start: number; end: number; value: string }[]; recognizer: 'phonetic' | 'pocketSphinx'; duration: number }
export async function analyzeSceneSpeech(wav: ArrayBuffer, signal?: AbortSignal, isolateVocals = false) {
  const data = await analyzeSceneSpeechDetailed(wav, { signal, isolateVocals })
  return parseMouthCues(data)
}

export async function analyzeSceneSpeechDetailed(wav: ArrayBuffer,
  options: { signal?: AbortSignal; isolateVocals?: boolean; dialogue?: string; language?: string } = {}) {
  const { signal, isolateVocals = false, dialogue, language = '' } = options
  const withScript = dialogue !== undefined
  let body: ArrayBuffer | string = wav
  if (withScript) {
    let binary = ''
    const bytes = new Uint8Array(wav)
    for (let i = 0; i < bytes.length; i += 8192) binary += String.fromCharCode(...bytes.subarray(i, i + 8192))
    body = JSON.stringify({ wavBase64: btoa(binary), dialogue, language })
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
