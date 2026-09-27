import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createMp4Muxer } from '../src/lib/mp4Muxer'

// Minimal H.264 High@4.0 SPS/PPS wrapped as an avcC decoder configuration record.
const sps = [0x67, 0x64, 0x00, 0x28, 0xac, 0xd9, 0x40, 0x78, 0x02, 0x27, 0xe5, 0x84, 0x00, 0x00, 0x03, 0x00, 0x04, 0x00, 0x00, 0x03, 0x00, 0xf0, 0x3c, 0x60, 0xc6, 0x58]
const pps = [0x68, 0xeb, 0xe3, 0xcb, 0x22, 0xc0]
const avcC = new Uint8Array([1, 0x64, 0x00, 0x28, 0xff, 0xe1, 0, sps.length, ...sps, 1, 0, pps.length, ...pps])

function chunk(type: 'key' | 'delta', timestamp: number, duration: number, bytes: number[]) {
  const data = new Uint8Array(bytes)
  return { type, timestamp, duration, byteLength: data.byteLength, copyTo: (dest: Uint8Array) => dest.set(data) } as unknown as EncodedVideoChunk
}

function hasBox(buffer: ArrayBuffer, name: string) {
  const bytes = new Uint8Array(buffer)
  const code = [...name].map(char => char.charCodeAt(0))
  return bytes.some((_, index) => code.every((value, offset) => bytes[index + offset] === value))
}

test('muxes WebCodecs-style H.264 chunks into a fast-start MP4', async () => {
  const muxer = await createMp4Muxer()
  const decoderConfig = { codec: 'avc1.640028', codedWidth: 1920, codedHeight: 1080, description: avcC }
  muxer.addVideoChunk(chunk('key', 0, 33333, [0, 0, 0, 2, 0x65, 0x88]), { decoderConfig })
  muxer.addVideoChunk(chunk('delta', 33333, 33333, [0, 0, 0, 2, 0x41, 0x9a]))
  const buffer = await muxer.finalize()

  assert.ok(buffer.byteLength > 0)
  assert.ok(hasBox(buffer, 'ftyp') && hasBox(buffer, 'moov') && hasBox(buffer, 'avcC'))
  // Fast start: the index (moov) precedes the media data (mdat).
  const text = new TextDecoder('latin1').decode(new Uint8Array(buffer))
  assert.ok(text.indexOf('moov') < text.indexOf('mdat'))
})

test('rejects audio chunks when the MP4 has no audio track', async () => {
  const muxer = await createMp4Muxer()
  assert.throws(() => muxer.addAudioChunk(chunk('key', 0, 21333, [1, 2])), /without an audio track/)
})

test('accepts all video before any audio without stalling', async () => {
  const muxer = await createMp4Muxer({ audio: true })
  const videoConfig = { codec: 'avc1.640028', codedWidth: 1920, codedHeight: 1080, description: avcC }
  // AAC-LC, 48 kHz, mono AudioSpecificConfig.
  const audioConfig = { codec: 'mp4a.40.2', sampleRate: 48000, numberOfChannels: 1, description: new Uint8Array([0x11, 0x88]) }
  for (let index = 0; index < 30; index += 1) {
    muxer.addVideoChunk(chunk(index === 0 ? 'key' : 'delta', index * 33333, 33333, [0, 0, 0, 2, 0x41, index]), index === 0 ? { decoderConfig: videoConfig } : undefined)
  }
  for (let index = 0; index < 47; index += 1) {
    muxer.addAudioChunk(chunk('key', Math.round(index * 1024 / 48000 * 1e6), 21333, [0x21, index]), index === 0 ? { decoderConfig: audioConfig } : undefined)
  }
  const buffer = await muxer.finalize()
  assert.ok(hasBox(buffer, 'avcC') && hasBox(buffer, 'esds'))
})
