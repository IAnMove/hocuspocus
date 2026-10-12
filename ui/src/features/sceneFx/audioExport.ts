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
  // 32-bit float PCM (WAVE_FORMAT_IEEE_FLOAT): peaks above 0 dBFS survive, so the server's limiter
  // (services/audio_mix.py) shapes them instead of the hard clip a 16-bit file would have baked in.
  const channels = Math.min(2, Math.max(1, buffer.numberOfChannels || 1))
  if (buffer.duration > 180 || channels < 1) throw new Error('Scene audio supports up to 180 stereo seconds.')
  const frames = buffer.getChannelData(0).length
  const bytes = new ArrayBuffer(44 + frames * channels * 4)
  const view = new DataView(bytes)
  const text = (at: number, value: string) => [...value].forEach((char, index) => view.setUint8(at + index, char.charCodeAt(0)))
  text(0, 'RIFF'); view.setUint32(4, bytes.byteLength - 8, true); text(8, 'WAVE'); text(12, 'fmt ')
  view.setUint32(16, 16, true); view.setUint16(20, 3, true); view.setUint16(22, channels, true)
  view.setUint32(24, buffer.sampleRate, true); view.setUint32(28, buffer.sampleRate * channels * 4, true)
  view.setUint16(32, channels * 4, true); view.setUint16(34, 32, true); text(36, 'data'); view.setUint32(40, frames * channels * 4, true)
  const planes = Array.from({ length: channels }, (_, index) => buffer.getChannelData(Math.min(index, buffer.numberOfChannels - 1)))
  for (let frame = 0; frame < frames; frame += 1) {
    for (let channel = 0; channel < channels; channel += 1) {
      view.setFloat32(44 + (frame * channels + channel) * 4, planes[channel][frame] ?? 0, true)
    }
  }
  return new Blob([bytes], { type: 'audio/wav' })
}

/** The WAV mix as a data URL, the form the owned-browser export bridges hand to the server. */
export async function sceneAudioWavDataUrl(buffer: AudioBuffer): Promise<string> {
  const bytes = new Uint8Array(await sceneAudioWav(buffer).arrayBuffer())
  let binary = ''
  for (let index = 0; index < bytes.length; index += 0x8000) binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000))
  return `data:audio/wav;base64,${btoa(binary)}`
}
