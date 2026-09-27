import type { ArrayBufferTarget, Muxer } from 'mp4-muxer'

/** Fail explicitly if AAC is unavailable; never publish a silently muted voice scene. */
export async function encodeSpeechAudio(muxer: Muxer<ArrayBufferTarget>, buffer: AudioBuffer) {
  if (typeof AudioEncoder === 'undefined' || typeof AudioData === 'undefined') throw new Error('AAC audio export needs a browser with AudioEncoder (Chrome/Edge).')
  const channels = buffer.numberOfChannels >= 2 ? 2 : 1
  const supported = await AudioEncoder.isConfigSupported({
    codec: 'mp4a.40.2',
    sampleRate: buffer.sampleRate,
    numberOfChannels: channels,
    bitrate: channels === 2 ? 160000 : 128000,
  })
  if (!supported.supported || !supported.config) throw new Error('AAC audio encoding is unavailable in this browser.')
  const encodedChannels = channels
  let failure: Error | undefined
  let wakeQueue: (() => void) | undefined
  const encoder = new AudioEncoder({
    output: (chunk, meta) => {
      try { muxer.addAudioChunk(chunk, meta) }
      catch (error) { failure = error instanceof Error ? error : new Error(String(error)); wakeQueue?.() }
    },
    error: error => { failure = error; wakeQueue?.() },
  })
  try {
    encoder.configure(supported.config)
    const sourceChannels = Math.max(1, buffer.numberOfChannels || 1)
    const planes = Array.from({ length: encodedChannels }, (_, index) => buffer.getChannelData(Math.min(index, sourceChannels - 1)))
    const samples = planes[0]
    for (let at = 0; at < samples.length; at += 1024) {
      if (failure) throw failure
      // Submit complete AAC-sized blocks; pad only the tail (at most 21.3 ms).
      const data = new Float32Array(1024 * encodedChannels)
      for (let channel = 0; channel < encodedChannels; channel += 1) {
        data.set(planes[channel].subarray(at, Math.min(at + 1024, planes[channel].length)), channel * 1024)
      }
      const audio = new AudioData({ format: 'f32-planar', sampleRate: buffer.sampleRate, numberOfFrames: 1024, numberOfChannels: encodedChannels,
        timestamp: Math.round(at / buffer.sampleRate * 1e6), data })
      try { encoder.encode(audio) } finally { audio.close() }
      // flush() is end-of-stream on some Windows AAC implementations. Use
      // dequeue for backpressure and flush ONCE, after the final PCM frame.
      if (encoder.encodeQueueSize > 32) await new Promise<void>(resolve => {
        const drained = () => { encoder.removeEventListener('dequeue', drained); wakeQueue = undefined; resolve() }
        wakeQueue = drained
        encoder.addEventListener('dequeue', drained, { once: true })
      })
    }
    await encoder.flush()
    if (failure) throw failure
  } finally { if (encoder.state !== 'closed') encoder.close() }
}
