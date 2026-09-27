/** Use native AAC when available; Linux browsers can finalize PCM through the app. */
export async function supportsSceneAac(channels = 1): Promise<boolean> {
  if (typeof AudioEncoder === 'undefined' || typeof AudioData === 'undefined') return false
  const numberOfChannels = channels >= 2 ? 2 : 1
  try {
    return (await AudioEncoder.isConfigSupported({
      codec: 'mp4a.40.2',
      sampleRate: 48000,
      numberOfChannels,
      bitrate: numberOfChannels === 2 ? 160000 : 128000,
    })).supported === true
  } catch { return false }
}

export function sceneAudioWav(buffer: AudioBuffer): Blob {
  const channels = Math.min(2, Math.max(1, buffer.numberOfChannels || 1))
  if (buffer.duration > 180 || channels < 1) throw new Error('Scene audio supports up to 180 stereo seconds.')
  const frames = buffer.getChannelData(0).length
  const bytes = new ArrayBuffer(44 + frames * channels * 2)
  const view = new DataView(bytes)
  const text = (at: number, value: string) => [...value].forEach((char, index) => view.setUint8(at + index, char.charCodeAt(0)))
  text(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true); text(8, 'WAVE'); text(12, 'fmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, channels, true)
  view.setUint32(24, buffer.sampleRate, true); view.setUint32(28, buffer.sampleRate * channels * 2, true)
  view.setUint16(32, channels * 2, true); view.setUint16(34, 16, true); text(36, 'data'); view.setUint32(40, frames * channels * 2, true)
  const planes = Array.from({ length: channels }, (_, index) => buffer.getChannelData(Math.min(index, buffer.numberOfChannels - 1)))
  for (let frame = 0; frame < frames; frame += 1) {
    for (let channel = 0; channel < channels; channel += 1) {
      view.setInt16(44 + (frame * channels + channel) * 2, Math.round(Math.max(-1, Math.min(1, planes[channel][frame] ?? 0)) * 32767), true)
    }
  }
  return new Blob([bytes], { type: 'audio/wav' })
}
