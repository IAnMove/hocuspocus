import { test } from 'node:test'
import assert from 'node:assert/strict'
import { soundtrackIsSceneTape } from '../src/features/scene3d/speech/audio'
import { buildSpeechProduction, queueSpeechProduction, takeSpeechProduction, type SpeechProductionInput } from '../src/features/scene3d/speech/production'
import { sceneVoiceTracks, speechEnd } from '../src/features/scene3d/speech/timeline'
import { parseScene3DDocument } from '../src/features/scene3d/document'
import { remountScene3DTemplate } from '../src/features/scene3d/templates'
import { amplitudeCues, mouthAt, parseMouthCues, parseSpeech } from '../src/features/scene3d/speech/track'
import { faceSettings, modelDigest } from '../src/features/scene3d/speech/profiles'

const asset = (filename: string) => ({ workspaceId: 'production', filename, url: '/api/v1/file/' + filename })
const input = (): SpeechProductionInput => ({
  kind: 'episode', title: 'A literal dialogue', sourceId: 'episode/shot-2', workspace: 'production', duration: 8, offset: 20,
  cast: [{ id: 'mira', name: 'Mira', model: asset('mira.glb') }, { id: 'innkeeper', name: 'Innkeeper', model: asset('innkeeper.glb') }],
  audio: asset('dialogue.wav'),
  lines: [{ id: 'a', characterId: 'mira', text: '¡Hola!', start: 0, end: 2 },
    { id: 'b', characterId: 'innkeeper', text: '¿Qué tal?', start: 2.5, end: 4 },
    { id: 'c', characterId: 'mira', text: 'Muy bien.', start: 5, end: 8 }],
})

test('production carries identity, literal dialogue, exact source offsets and one audible soundtrack', () => {
  const doc = buildSpeechProduction(input()), [mira, innkeeper] = doc.slots
  assert.deepEqual(mira.character, { id: 'mira', name: 'Mira' })
  assert.deepEqual(mira.sourceRef, { ...input().cast[0].model, assetId: undefined })
  assert.deepEqual(mira.speech!.clips!.map(c => [c.id, c.text, c.start, c.end, c.offset, c.audible]),
    [['a', '¡Hola!', 0, 2, 20, false], ['c', 'Muy bien.', 5, 8, 25, false]])
  assert.equal(innkeeper.speech!.clips![0].offset, 22.5)
  assert.equal(sceneVoiceTracks(doc).length, 1)
  assert.equal(sceneVoiceTracks(doc)[0].offset, 20)
  assert.equal(soundtrackIsSceneTape(doc.soundtrack![0].audio.url, doc), true)
  assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(doc))), doc)
  assert.equal(speechEnd(mira.speech!), 8)
})

test('repeated phrases and gaps are deterministic, end exclusive, and never drive the wrong speaker', () => {
  const doc = buildSpeechProduction(input()), speech = doc.slots[0].speech!
  speech.clips![0].cues = [{ start: 20, end: 22, viseme: 'A' }]
  speech.clips![1].cues = [{ start: 25, end: 28, viseme: 'M' }]
  assert.equal(mouthAt(speech, .2).b, 2)
  for (const time of [2, 3, 4.99, 8, -1]) assert.deepEqual(mouthAt(speech, time), { a: 0, b: 0, mix: 1 })
  assert.equal(mouthAt(speech, 5.2).b, 1)
  const times = [.01, 1, 2.1, 5, 7.5, 8]
  assert.deepEqual(times.map(t => mouthAt(speech, t)), [...times].reverse().map(t => mouthAt(speech, t)).reverse())
  assert.equal(mouthAt({ ...speech, enabled: false }, 5.2).b, 0)
})

test('invalid timing, overlapping turns, identities and unsafe assets cannot enter a scene', () => {
  const value = input()
  for (const change of [{ duration: 91 }, { duration: NaN }, { offset: -1 }, { offset: 599 },
    { cast: [...value.cast, value.cast[0]] }, { audio: { ...value.audio, url: 'file:///secret.wav' } },
    { lines: [{ id: 'x', characterId: 'missing', text: '?' }] },
    { lines: [{ id: 'x', characterId: 'mira', text: 'x', start: 3, end: 2 }] },
    { lines: [...value.lines!, { id: 'z', characterId: 'mira', text: 'x', start: 1, end: 3 }] }]) {
    assert.throws(() => buildSpeechProduction({ ...value, ...change }))
  }
  const speech = buildSpeechProduction(value).slots[0].speech!
  assert.throws(() => parseSpeech({ ...speech, clips: [speech.clips![0], speech.clips![0]] }))
})

test('un-timed episode lines get editable initial ranges, not fabricated recognition', () => {
  const value = input()
  const doc = buildSpeechProduction({ ...value, lines: value.lines!.map(({ id, characterId, text }) => ({ id, characterId, text })) })
  assert.equal(doc.slots[0].speech!.clips![0].end, 8 / 3)
  assert.equal(doc.slots[1].speech!.clips![0].start, 8 / 3)
  assert.equal(doc.slots[0].speech!.clips![0].driver, 'imported')
  assert.deepEqual(doc.slots[0].speech!.clips![0].cues, [])
})

test('song can crop original audio without a duplicate vocal and remount keeps production data', () => {
  const value = input()
  const doc = buildSpeechProduction({ ...value, kind: 'song', cast: [value.cast[0]], lines: undefined })
  const next = remountScene3DTemplate('speech-presenter', doc, true)
  assert.equal(next.duration, 8)
  assert.deepEqual(next.production, doc.production)
  assert.deepEqual(next.soundtrack, doc.soundtrack)
  assert.deepEqual(next.slots[0].character, doc.slots[0].character)
  assert.deepEqual(next.slots[0].speech, doc.slots[0].speech)
  assert.notEqual(next.slots[0].speech, doc.slots[0].speech)
  assert.equal(sceneVoiceTracks(next).length, 1)
  next.soundtrack![0].gain = 0
  assert.equal(doc.soundtrack![0].gain, 1)
  assert.equal(next.slots[0].speech!.enabled, true)
})

test('handoff stays in its workspace and is not consumed when backup fails', () => {
  const items = new Map<string, string>()
  const storage = { setItem: (k: string, v: string) => items.set(k, v), getItem: (k: string) => items.get(k) ?? null, removeItem: (k: string) => items.delete(k) }
  const doc = buildSpeechProduction(input())
  queueSpeechProduction(doc, storage)
  assert.equal(takeSpeechProduction('another-workspace', storage), null)
  assert.deepEqual(takeSpeechProduction('production', storage), doc)
  assert.equal(takeSpeechProduction('production', storage), null)
  // A backup that fails (storage quota) must not leave the handoff behind,
  // or every later event would replay the failure.
  queueSpeechProduction(doc, storage)
  assert.throws(() => takeSpeechProduction('production', storage, () => { throw new Error('QuotaExceeded') }))
  assert.equal(takeSpeechProduction('production', storage), null)
})

test('reusable face profiles never copy dialogue, voice sources or timing', () => {
  const speech = buildSpeechProduction(input()).slots[0].speech!
  const settings = faceSettings(speech)
  for (const key of ['audio', 'clips', 'cues', 'start', 'end', 'offset', 'gain', 'enabled']) assert.equal(key in settings, false)
})

test('model identity is content-addressed across upload URLs', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async (url) => new Response(String(url).includes('different') ? 'other GLB bytes' : 'same GLB bytes')
  try {
    const a = await modelDigest('/test/mira-upload-a.glb')
    assert.match(a, /^[a-f0-9]{64}$/)
    assert.equal(a, await modelDigest('/test/mira-upload-b.glb'))
    assert.notEqual(a, await modelDigest('/test/different.glb'))
  } finally { globalThis.fetch = original }
})

test('amplitude fallback keeps the original source clock and bounds ten-minute tracks', () => {
  const buffer = { sampleRate: 300, duration: 600, getChannelData: () => new Float32Array(180000) } as unknown as AudioBuffer
  assert.deepEqual(amplitudeCues(buffer, 120, 8), [{ start: 120, end: 128, viseme: 'rest' }])
  assert.ok(parseMouthCues(amplitudeCues(buffer)).length <= 10000)
})
