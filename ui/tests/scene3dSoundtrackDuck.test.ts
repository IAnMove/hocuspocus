import { afterEach, test } from 'node:test'
import assert from 'node:assert/strict'
import {
  mixSceneSpeech,
  resetVoiceDecodeCache,
  soundtrackGainAt,
  soundtrackGainCurve,
  soundtrackIsSceneTape,
  SOUNDTRACK_DUCK_DB,
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

const DUCK_LINEAR = 10 ** (-SOUNDTRACK_DUCK_DB / 20)
const WINDOW = { start: 1.5, end: 2.5 }

function rms(start: number, end: number, windows: { start: number; end: number }[]) {
  const rate = 48000
  let energy = 0
  let count = 0
  for (let index = Math.ceil(start * rate); index < Math.floor(end * rate); index += 1) {
    const gain = soundtrackGainAt(index / rate, 1, 0, 4, windows)
    energy += gain * gain
    count += 1
  }
  return Math.sqrt(energy / count)
}

test('music under dialogue falls by at least 8 dB and the rest stays within 0.5 dB', () => {
  const full = rms(0.5, 1.2, [])
  const outside = rms(0.5, 1.2, [WINDOW])
  const under = rms(1.8, 2.2, [WINDOW])
  const outsideDb = 20 * Math.log10(outside / full)
  const duckedDb = 20 * Math.log10(under / outside)
  console.log(`soundtrack duck ${duckedDb.toFixed(3)} dB; outside ${outsideDb.toFixed(3)} dB; linear ${DUCK_LINEAR.toFixed(6)}`)
  assert.ok(Math.abs(outsideDb) <= 0.5, `outside changed by ${outsideDb} dB`)
  assert.ok(duckedDb <= -8, `dialogue only ducked ${duckedDb} dB`)
  assert.ok(Math.abs(soundtrackGainAt(0, 1, 0, 4, []) - 0) < 1e-9)
  assert.ok(Math.abs(soundtrackGainAt(0.06, 1, 0, 4, []) - 0.5) < 1e-9)
})

test('the same dialogue renders the same soundtrack curve twice', () => {
  const first = soundtrackGainCurve(0, 4, 1, [WINDOW])
  const second = soundtrackGainCurve(0, 4, 1, [WINDOW])
  assert.deepEqual(second, first)
  const index = Math.round((2 / 4) * (first.length - 1))
  assert.ok(Math.abs(first[index] - DUCK_LINEAR) < 1e-6)
})

test('an export schedules the ducked curve and ignores inaudible lip-sync', async () => {
  const curves: Float32Array[] = []
  class FakeOfflineAudioContext {
    destination = {}
    constructor(public numberOfChannels = 1, public length = 1, public sampleRate = 48000) {}
    decodeAudioData() {
      return { duration: 8, sampleRate: 48000, length: 8, numberOfChannels: 1, getChannelData: () => new Float32Array(8) }
    }
    createBufferSource() { return { buffer: null as AudioBuffer | null, playbackRate: { value: 1 }, connect() {}, start() {} } }
    createGain() {
      return { gain: { value: 1, setValueCurveAtTime: (curve: Float32Array) => { curves.push(curve) } }, connect() {} }
    }
    startRendering() {
      return { duration: this.length / this.sampleRate, sampleRate: this.sampleRate, numberOfChannels: this.numberOfChannels,
        getChannelData: () => new Float32Array(this.length) }
    }
  }
  Object.defineProperty(globalThis, 'OfflineAudioContext', { configurable: true, value: FakeOfflineAudioContext })
  globalThis.fetch = async () => new Response(new Uint8Array(64), { status: 200, headers: { 'content-length': '64' } })
  const audio = { url: '/api/v1/file/bed.wav', workspaceId: 'w', filename: 'bed.wav' }
  const voice = { url: '/api/v1/file/line.wav', workspaceId: 'w', filename: 'line.wav' }
  const document = {
    duration: 4,
    soundtrack: [{ id: 'bed', audio, start: 0, offset: 0, gain: 1, end: 4 }],
    slots: [{
      id: 'lead',
      speech: {
        enabled: true, audio: voice, cues: [], driver: 'imported', start: 1.5, offset: 0, gain: 1, end: 2.5,
      },
    }],
  } as unknown as Scene3DDocument
  await mixSceneSpeech(document)
  await mixSceneSpeech(document)
  assert.equal(curves.length, 2)
  assert.deepEqual(curves[1], curves[0])
  const spoken = curves[0]
  const at = (time: number) => spoken[Math.round((time / 4) * (spoken.length - 1))]
  assert.ok(Math.abs(at(2) - DUCK_LINEAR) < 1e-6)
  assert.ok(Math.abs(at(0.8) - 1) < 1e-6)

  curves.length = 0
  const silent = structuredClone(document) as Scene3DDocument
  silent.slots[0].speech!.audible = false
  await mixSceneSpeech(silent)
  assert.ok(Math.abs(curves[0][Math.round((2 / 4) * (curves[0].length - 1))] - 1) < 1e-6)
})

test('the scene tape is not a music bed: no fade and no duck against its own lip-sync', async () => {
  const tape = { url: '/api/v1/file/dialogue.wav', workspaceId: 'w', filename: 'dialogue.wav' }
  const voice = { url: '/api/v1/file/line.wav', workspaceId: 'w', filename: 'line.wav' }
  const production = {
    duration: 4,
    soundtrack: [{ id: 'production-audio', audio: tape, start: 0, offset: 0, gain: 1, end: 4 }],
    slots: [{
      id: 'lead',
      speech: {
        enabled: true,
        clips: [{
          id: 'hola', audio: tape, cues: [], driver: 'imported', start: 0, offset: 0, gain: 1, end: 4, audible: false,
        }],
      },
    }],
  } as unknown as Scene3DDocument
  assert.equal(soundtrackIsSceneTape(tape.url, production), true)
  assert.equal(soundtrackIsSceneTape(voice.url, production), false)
  assert.equal(soundtrackGainAt(0, 1, 0, 4, [], false), 1)
  assert.equal(soundtrackGainAt(0.06, 1, 0, 4, [], false), 1)
  assert.equal(soundtrackGainAt(3.9, 1, 0, 4, [], false), 1)

  const curves: Float32Array[] = []
  const fixed: number[] = []
  class FakeOfflineAudioContext {
    destination = {}
    constructor(public numberOfChannels = 1, public length = 1, public sampleRate = 48000) {}
    decodeAudioData() {
      return { duration: 8, sampleRate: 48000, length: 8, numberOfChannels: 1, getChannelData: () => new Float32Array(8) }
    }
    createBufferSource() { return { buffer: null as AudioBuffer | null, playbackRate: { value: 1 }, connect() {}, start() {} } }
    createGain() {
      return {
        gain: {
          set value(next: number) { fixed.push(next) },
          setValueCurveAtTime: (curve: Float32Array) => { curves.push(curve) },
        },
        connect() {},
      }
    }
    startRendering() {
      return { duration: this.length / this.sampleRate, sampleRate: this.sampleRate, numberOfChannels: this.numberOfChannels,
        getChannelData: () => new Float32Array(this.length) }
    }
  }
  Object.defineProperty(globalThis, 'OfflineAudioContext', { configurable: true, value: FakeOfflineAudioContext })
  globalThis.fetch = async () => new Response(new Uint8Array(64), { status: 200, headers: { 'content-length': '64' } })

  await mixSceneSpeech(production)
  assert.equal(curves.length, 0)
  assert.deepEqual(fixed, [1])

  const overdub = structuredClone(production) as Scene3DDocument
  overdub.slots.push({
    id: 'over',
    speech: {
      enabled: true, audio: voice, cues: [], driver: 'imported', start: 1.5, offset: 0, gain: 1, end: 2.5,
    },
  } as Scene3DDocument['slots'][number])
  curves.length = 0
  fixed.length = 0
  await mixSceneSpeech(overdub)
  assert.equal(curves.length, 1)
  const at = (time: number) => curves[0][Math.round((time / 4) * (curves[0].length - 1))]
  assert.ok(Math.abs(at(0) - 1) < 1e-6, `tape start was faded to ${at(0)}`)
  assert.ok(Math.abs(at(0.06) - 1) < 1e-6, `tape attack was faded to ${at(0.06)}`)
  assert.ok(Math.abs(at(2) - DUCK_LINEAR) < 1e-6)
  assert.ok(Math.abs(at(3.9) - 1) < 1e-6, `tape tail was faded to ${at(3.9)}`)
})
