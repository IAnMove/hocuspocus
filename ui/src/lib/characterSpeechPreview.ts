import { analyzeSceneSpeechDetailed } from '../api/scene3dSpeech'
import { getFileUrl } from '../api/client'
import { decodeVoice, voiceWav } from '../features/scene3d/speech/audio'
import { generateSceneSpeechClip } from './sceneSpeech'
import { previewFaceRigDialogueFromCues } from './characterKitFaceRig'
import type { CharacterKit } from './characterKit'

export const characterSpeechPreviewServices = {
  generate: generateSceneSpeechClip, decode: decodeVoice, wav: voiceWav, analyze: analyzeSceneSpeechDetailed,
}

export function speechPreviewDuration(text: string) {
  const words = text.trim().split(/\s+/).filter(Boolean).length
  const pauses = (text.match(/[.,;:!?]/g) ?? []).length
  return Math.min(90, Math.max(3, Math.ceil(words / 2 + pauses * .3 + 1)))
}

/** Same isolated-audio analyzer as native shots; failed analysis is never a text-timed success. */
export async function createCharacterSpeechPreview(options: {
  kit: CharacterKit; text: string; model: string; workspace: string; language: string; signal: AbortSignal
}, services = characterSpeechPreviewServices) {
  const { kit, workspace, language, signal } = options
  const text = options.text.trim()
  const clip = await services.generate({ prompt: text, model: kit.voice?.model || options.model,
    voice: kit.voice, workspace, signal, durationSeconds: speechPreviewDuration(text) })
  signal.throwIfAborted()
  const buffer = await services.decode(getFileUrl(clip.filename, workspace), signal)
  const wav = await services.wav(buffer)
  signal.throwIfAborted()
  const analysis = await services.analyze(wav, { dialogue: text, language, signal })
  signal.throwIfAborted()
  return { filename: clip.filename, preview: previewFaceRigDialogueFromCues(kit, text, analysis, buffer.duration) }
}
