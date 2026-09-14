import { uploadLocalAsset } from '../asset-picker/upload'
import { voiceWav } from '../scene3d/speech/audio'

/** Normalize both browser recordings and imported audio before storing a reusable voice. */
export async function uploadVoiceReference(blob: Blob, signal: AbortSignal): Promise<string> {
  if (!blob.size || blob.size > 20 * 1024 * 1024) throw new Error('voiceFileSize')
  signal.throwIfAborted()
  let buffer: AudioBuffer
  try { buffer = await new OfflineAudioContext(1, 1, 24000).decodeAudioData(await blob.arrayBuffer()) }
  catch { throw new Error('voiceFileDecode') }
  signal.throwIfAborted()
  if (!Number.isFinite(buffer.duration) || buffer.duration < 3 || buffer.duration > 30) throw new Error('voiceFileDuration')
  const wav = await voiceWav(buffer)
  signal.throwIfAborted()
  const uploaded = await uploadLocalAsset(new File([wav], 'voice-reference.wav', { type: 'audio/wav' }), signal)
  return uploaded.url
}
