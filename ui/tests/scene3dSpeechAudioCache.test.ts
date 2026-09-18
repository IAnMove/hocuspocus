import { afterEach, test } from 'node:test'
import assert from 'node:assert/strict'
import {
  decodeVoice,
  MAX_DECODED_VOICES,
  mixSceneSpeech,
  resetVoiceDecodeCache,
  voiceDecodeCacheHas,
  voiceDecodeCacheSize,
  voiceWav,
} from '../src/features/scene3d/speech/audio'
import type { Scene3DDocument } from '../src/features/scene3d/types'

const originalFetch = globalThis.fetch
const originalContext = Object.getOwnPropertyDescriptor(globalThis, 'OfflineAudioContext')

afterEach(() => {
  resetVoiceDecodeCache()
  globalThis.fetch = originalFetch
  if (originalContext) Object.defineProperty(globalThis, 'OfflineAudioContext', originalContext)
  else Reflect.deleteProperty(globalThis, 'OfflineAudioContext')
})

function installAudio() {
  class FakeOfflineAudioContext {
    destination = {}
    constructor(public numberOfChannels = 1, public length = 1, public sampleRate = 48000) {}
    decodeAudioData() {
      const samples = new Float32Array(Math.max(1, this.sampleRate * 2))
      return { duration: 2, sampleRate: this.sampleRate, length: samples.length, numberOfChannels: 1, getChannelData: () => samples }
    }
    createBufferSource() { return { buffer: null as AudioBuffer | null, playbackRate: { value: 1 }, connect() {}, start() {} } }
    createGain() { return { gain: { value: 1 }, connect() {} } }
    startRendering() {
      return { duration: this.length / this.sampleRate, sampleRate: this.sampleRate, numberOfChannels: 1,
        getChannelData: () => new Float32Array(this.length) }
    }
  }
  Object.defineProperty(globalThis, 'OfflineAudioContext', { configurable: true, value: FakeOfflineAudioContext })
}

function stubFetch(onRequest?: (url: string, init?: RequestInit) => void) {
  const fetches: string[] = []
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input)
    fetches.push(url)
    onRequest?.(url, init)
    if (init?.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    return new Response(new Uint8Array(64), { status: 200, headers: { 'content-length': '64' } })
  }
  return fetches
}

test('three shots of the same source decode once and keep original audio', async () => {
  installAudio()
  const fetches = stubFetch()
  const url = '/api/v1/file/h07-song.wav'
  const buffers = await Promise.all([decodeVoice(url), decodeVoice(url), decodeVoice(url)])
  assert.equal(fetches.length, 1)
  assert.equal(buffers[0], buffers[1])
  assert.equal(buffers[1], buffers[2])
  await voiceWav(buffers[0], 0, 1)
  await voiceWav(buffers[0], 0.5, 1)
  assert.equal(fetches.length, 1)
  assert.equal(voiceDecodeCacheSize(), 1)
})

test('simultaneous decodes share one request and aborting one consumer keeps the other', async () => {
  installAudio()
  let release: ((value: Response) => void) | undefined
  const fetches: string[] = []
  globalThis.fetch = input => new Promise(resolve => {
    fetches.push(String(input))
    release = resolve
  })
  const url = '/api/v1/file/h07-shared.wav'
  const cancelled = new AbortController()
  const first = decodeVoice(url, cancelled.signal)
  const second = decodeVoice(url)
  cancelled.abort()
  release!(new Response(new Uint8Array(64), { status: 200, headers: { 'content-length': '64' } }))
  await assert.rejects(first, /Abort/)
  const kept = await second
  assert.equal(kept.duration, 2)
  assert.equal(fetches.length, 1)
  assert.equal(voiceDecodeCacheSize(), 1)
})

test('bounded cache releases idle decoders and does not evict an in-use buffer', async () => {
  installAudio()
  const fetches: string[] = []
  let releaseKeep: ((value: Response) => void) | undefined
  const keepUrl = '/api/v1/file/h07-keep.wav'
  globalThis.fetch = input => {
    const url = String(input)
    fetches.push(url)
    if (url === keepUrl && !releaseKeep) return new Promise(resolve => { releaseKeep = resolve })
    return Promise.resolve(new Response(new Uint8Array(64), { status: 200, headers: { 'content-length': '64' } }))
  }
  const pending = decodeVoice(keepUrl)
  for (let i = 0; i < MAX_DECODED_VOICES; i++) await decodeVoice(`/api/v1/file/h07-fill-${i}.wav`)
  assert.equal(fetches.filter(url => url === keepUrl).length, 1)
  assert.equal(voiceDecodeCacheHas(keepUrl), true)
  releaseKeep!(new Response(new Uint8Array(64), { status: 200, headers: { 'content-length': '64' } }))
  await pending
  await decodeVoice('/api/v1/file/h07-extra.wav')
  assert.ok(voiceDecodeCacheSize() <= MAX_DECODED_VOICES)
})

test('mix keeps the original soundtrack and never fetches isolated vocals', async () => {
  installAudio()
  const fetches = stubFetch()
  const song = '/api/v1/file/h07-soundtrack.wav'
  const vocals = '/api/v1/file/h07-isolated-vocals.wav'
  const document = {
    duration: 2,
    soundtrack: [{ id: 'song', audio: { url: song, workspaceId: 'w', filename: 'h07-soundtrack.wav' }, start: 0, offset: 0.25, gain: 1, end: 2 }],
    slots: [{
      id: 'subject_1',
      speech: {
        enabled: true, audible: false, audio: { url: song, workspaceId: 'w', filename: 'h07-soundtrack.wav' },
        cues: [{ start: 0.25, end: 1.2, viseme: 'A' }], driver: 'rhubarb-vocals', start: 0, offset: 0.25, gain: 1, end: 2,
      },
    }],
  } as unknown as Scene3DDocument
  const mixed = await mixSceneSpeech(document)
  assert.ok(mixed)
  assert.deepEqual(fetches, [song])
  assert.equal(fetches.includes(vocals), false)
})
