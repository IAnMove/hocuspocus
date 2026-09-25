import assert from 'node:assert/strict'
import test from 'node:test'
import { analyzeNativeSpeech } from '../src/features/series/nativeSpeechAnalysis'
import type { Scene } from '../src/types'

test('native regeneration analyzes the exact isolated voice fragment with its script, retaining the original soundtrack', async () => {
  const scene = { version: 1, duration: 5, fps: 30, layers: [],
    audioTracks: [{ id: 'voice', filename: 'voice.wav', kind: 'speech', startTime: 1, prompt: 'Move now.', volume: 1 },
      { id: 'music', filename: 'music.mp3', kind: 'music', startTime: 0, volume: .1 }],
    dialogueBeats: [{ id: 'line', text: 'Move now.', start: 1.5, end: 3.5, mouthLayerIds: ['mouth'], audioTrackId: 'voice', confidence: 'known-text' },
      { id: 'offscreen', text: 'Hello', start: 4, end: 5, mouthLayerIds: [], confidence: 'known-text' }],
  } as Scene
  const before = structuredClone(scene), buffer = { duration: 4 } as AudioBuffer
  let analyses = 0
  const result = await analyzeNativeSpeech(scene, 'source', 'en', {
    decode: async url => { assert.match(url, /voice\.wav/); assert.match(url, /source/); return buffer },
    wav: async (actual, offset, duration) => { assert.equal(actual, buffer); assert.equal(offset, .5); assert.equal(duration, 2); return new ArrayBuffer(8) },
    analyze: async (_wav, options) => { analyses++; assert.equal(options?.dialogue, 'Move now.'); assert.equal(options?.language, 'en');
      return { recognizer: 'pocketSphinx', duration: 2, mouthCues: [{ start: .1, end: .2, value: 'A' }, { start: .2, end: 1, value: 'F' }] } },
  })
  assert.equal(analyses, 1)
  assert.deepEqual(scene, before)
  assert.deepEqual(result.audioTracks, before.audioTracks)
  assert.equal(result.dialogueBeats![0].lipSync!.cues[0].viseme, 'M')
  assert.equal(result.dialogueBeats![1].lipSync, undefined)
})

test('unavailable phonetic analysis is an explicit error, never a successful letter-timed result', async () => {
  const scene = { duration: 3, layers: [], audioTracks: [{ id: 'voice', filename: 'voice.wav', startTime: 0, prompt: 'Hi' }],
    dialogueBeats: [{ id: 'line', text: 'Hi', start: 0, end: 2, mouthLayerIds: ['mouth'], audioTrackId: 'voice', confidence: 'known-text' }] } as unknown as Scene
  await assert.rejects(analyzeNativeSpeech(scene, 'source', 'es', { decode: async () => ({ duration: 2 }) as AudioBuffer,
    wav: async () => new ArrayBuffer(8), analyze: async () => { throw new Error('Rhubarb is unavailable') } }), /Rhubarb/)
})
