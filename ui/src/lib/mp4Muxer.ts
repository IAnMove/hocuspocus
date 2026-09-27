import {
  BufferTarget,
  EncodedAudioPacketSource,
  EncodedPacket,
  EncodedVideoPacketSource,
  Mp4OutputFormat,
  Output,
} from 'mediabunny'

type EncodedChunk = Pick<EncodedVideoChunk | EncodedAudioChunk, 'type' | 'timestamp' | 'duration' | 'byteLength' | 'copyTo'>

/**
 * H.264 (+ optional AAC) MP4 muxer fed directly from WebCodecs encoder
 * callbacks. Those callbacks are synchronous while Mediabunny's sources are
 * async, so chunks are copied immediately and written in order per track;
 * any muxing error is reported by `finalize()`.
 */
export interface Mp4Muxer {
  addVideoChunk(chunk: EncodedChunk, meta?: EncodedVideoChunkMetadata): void
  addAudioChunk(chunk: EncodedChunk, meta?: EncodedAudioChunkMetadata): void
  /** Wait for every queued chunk, then return the complete MP4 file. */
  finalize(): Promise<ArrayBuffer>
}

function toPacket(chunk: EncodedChunk): EncodedPacket {
  const data = new Uint8Array(chunk.byteLength)
  chunk.copyTo(data)
  return new EncodedPacket(data, chunk.type, chunk.timestamp / 1e6, (chunk.duration ?? 0) / 1e6)
}

export async function createMp4Muxer(options: { audio?: boolean } = {}): Promise<Mp4Muxer> {
  const output = new Output({
    format: new Mp4OutputFormat({ fastStart: 'in-memory' }),
    target: new BufferTarget(),
  })
  const video = new EncodedVideoPacketSource('avc')
  output.addVideoTrack(video)
  const audio = options.audio ? new EncodedAudioPacketSource('aac') : null
  if (audio) output.addAudioTrack(audio)
  await output.start()

  let failure: unknown = null
  let videoQueue: Promise<void> = Promise.resolve()
  let audioQueue: Promise<void> = Promise.resolve()
  const recordFailure = (error: unknown) => { failure ??= error }

  return {
    addVideoChunk(chunk, meta) {
      if (failure) throw failure
      const packet = toPacket(chunk)
      videoQueue = videoQueue.then(() => video.add(packet, meta)).catch(recordFailure)
    },
    addAudioChunk(chunk, meta) {
      if (failure) throw failure
      if (!audio) throw new Error('This MP4 was created without an audio track.')
      const packet = toPacket(chunk)
      audioQueue = audioQueue.then(() => audio.add(packet, meta)).catch(recordFailure)
    },
    async finalize() {
      await Promise.all([videoQueue, audioQueue])
      if (failure) throw failure
      await output.finalize()
      const buffer = output.target.buffer
      if (!buffer) throw new Error('The MP4 muxer produced no data.')
      return buffer
    },
  }
}
