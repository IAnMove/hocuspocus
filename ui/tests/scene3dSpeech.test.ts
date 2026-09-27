import { test } from 'node:test'
import assert from 'node:assert/strict'
import { Object3D } from 'three'
import { defaultSpeech, VISEMES } from '../src/features/scene3d/speech/types'
import { cueAt, expressionAt, mouthAt, parseExpressionCues, parseMouthCues, parseSpeech, amplitudeCues, safeMediaUrl } from '../src/features/scene3d/speech/track'
import { FACE_PACK_SCREEN_ERROR, FacePackRuntime, facePackCell, validFacePackSize } from '../src/features/scene3d/speech/facePack'
import { FACE_PACK_IDS, talkingMascot } from '../src/features/scene3d/speech/facePackExamples'
import { speechFromLabConfig } from '../src/features/scene3d/speech/kit'
import { voiceSchedule } from '../src/features/scene3d/speech/audio'
import { applyScene3DTemplate, remountScene3DTemplate } from '../src/features/scene3d/templates'
import { parseScene3DDocument } from '../src/features/scene3d/document'
import { worldAssetsReady } from '../src/features/scene3d/gpu'

const face = { meshIndex: 0, center: [0, 1.5, .1], size: [.1, .08], skin: [.5, .3, .2],
  eyes: { left: [-.04, 1.55, .1], right: [.04, 1.55, .1], size: [.04, .02], skinLeft: [.5, .3, .2], skinRight: [.5, .3, .2] } }
const speech = () => parseSpeech({ ...defaultSpeech(), face, cues: [{ start: 0, end: 1, viseme: 'A' }, { start: 1.5, end: 2, viseme: 'M' }],
  audio: { workspaceId: 'test', filename: 'voice.wav', url: '/api/voice.wav' } })!

test('Rhubarb shapes map to the same nine Taberna mouth drawings', () => {
  const shapes = [...'XABCDEFGH']
  assert.deepEqual(parseMouthCues({ mouthCues: shapes.map((value, i) => ({ start: i, end: i + 1, value })) }).map(c => c.viseme), ['rest', 'M', 'I', 'E', 'A', 'O', 'U', 'F', 'L'])
})
test('reject malformed, overlapping and oversized tracks and unsafe media', () => {
  for (const raw of [[{ start: -1, end: 1, viseme: 'A' }], [{ start: 0, end: Infinity, viseme: 'A' }],
    [{ start: 0, end: 1, viseme: 'A' }, { start: .5, end: 2, viseme: 'M' }], Array(10001).fill({})]) assert.throws(() => parseMouthCues(raw))
  for (const url of ['javascript:alert(1)', 'blob:test', '//evil.test/file', 'file:///C:/secret']) {
    assert.equal(safeMediaUrl(url), false)
    assert.throws(() => parseSpeech({ ...speech(), audio: { workspaceId: 'x', filename: 'x', url } }))
  }
  assert.throws(() => parseSpeech({ ...speech(), face: { ...face, size: [0, .2] } }))
  assert.throws(() => parseSpeech({ ...speech(), gain: 4 }))
})
test('silence, end-exclusive cues, offsets and disabled face are deterministic', () => {
  const value = speech()
  assert.equal(cueAt(value.cues, 1), 'rest')
  assert.equal(cueAt(value.cues, 1.6), 'M')
  assert.equal(cueAt(value.cues, 2), 'rest')
  const forward = [0, .03, .2, 1, 1.51, 3].map(t => mouthAt(value, t))
  assert.deepEqual([3, 1.51, 1, .2, .03, 0].map(t => mouthAt(value, t)).reverse(), forward)
  assert.deepEqual(mouthAt({ ...value, start: 4 }, 3), { a: 0, b: 0, mix: 1 })
  assert.equal(mouthAt({ ...value, start: 4, offset: 1.6 }, 4.1).b, 1)
  assert.deepEqual(mouthAt({ ...value, enabled: false }, .5), { a: 0, b: 0, mix: 1 })
})
test('all three new scenes round-trip with independent speaker tracks', () => {
  for (const id of ['speech-portrait', 'speech-dialogue', 'speech-presenter'] as const) {
    const doc = applyScene3DTemplate(id)
    doc.slots.forEach((slot, i) => { slot.sourceUrl = '/api/character.glb'; slot.speech = { ...speech(), start: i * 3 } })
    assert.deepEqual(parseScene3DDocument(JSON.parse(JSON.stringify(doc)))?.slots.map(s => s.speech), doc.slots.map(s => s.speech))
    assert.equal(parseScene3DDocument({ ...doc, slots: [{ ...doc.slots[0], speech: { ...speech(), offset: -1 } }] }), null)
  }
})
test('keep-assets carries voice/calibration by role without sharing mutable objects', () => {
  const original = applyScene3DTemplate('speech-dialogue')
  original.slots[0].sourceUrl = '/api/model.glb'; original.slots[0].speech = speech()
  const next = remountScene3DTemplate('speech-portrait', original, true)
  assert.deepEqual(next.slots[0].speech, original.slots[0].speech)
  assert.notEqual(next.slots[0].speech, original.slots[0].speech)
  assert.equal(remountScene3DTemplate('speech-portrait', original, false).slots[0].speech, undefined)
})
test('legacy silent scenes remain valid without speech', () => {
  assert.ok(parseScene3DDocument(applyScene3DTemplate('two-shot')))
  assert.equal(parseScene3DDocument(applyScene3DTemplate('two-shot'))?.slots[0].speech, undefined)
})
test('Taberna v2 placement and eye settings convert without applying offsets twice', () => {
  const imported = speechFromLabConfig({ type: 'taberna-talking-character', version: 2,
    anchor: { center: face.center, width: .1, height: .08 }, skin: face.skin, eyes: face.eyes,
    track: { cues: speech().cues }, settings: { expression: 'happy', strength: .75, eyes: false } })
  assert.deepEqual(imported.face, face); assert.equal(imported.expression, 'happy'); assert.equal(imported.eyes, false)
  assert.throws(() => speechFromLabConfig({ version: 1 }))
})
test('export voice schedule uses scene speed exactly once and clips to scene end', () => {
  assert.deepEqual(voiceSchedule(4, 1, 10, 8, 2), { when: 2, offset: 1, rate: 2, duration: 4 })
  assert.equal(voiceSchedule(12, 0, 10, 8, .5).duration, 0)
})
test('volume fallback is explicitly approximate and detects silence', () => {
  const buffer = { sampleRate: 300, duration: 1, getChannelData: () => new Float32Array(300) } as unknown as AudioBuffer
  assert.deepEqual(amplitudeCues(buffer), [{ start: 0, end: 1, viseme: 'rest' }])
})
test('expression cues sample like mouth cues and fall back to the static expression', () => {
  const value = parseSpeech({
    ...speech(),
    expression: 'neutral',
    expressionCues: [{ start: 0.2, end: 1, expression: 'happy' }, { start: 1.2, end: 2, expression: 'angry' }],
  })!
  assert.equal(expressionAt(value, 0), 'neutral')
  assert.equal(expressionAt(value, 0.5), 'happy')
  assert.equal(expressionAt(value, 1), 'neutral')
  assert.equal(expressionAt(value, 1.5), 'angry')
  assert.equal(expressionAt({ ...value, enabled: false }, 0.5), 'neutral')
  assert.throws(() => parseExpressionCues([{ start: 0, end: 1, expression: 'happy' }, { start: 0.5, end: 2, expression: 'angry' }]))
})
test('face packs are 9×6 and talking mascots round-trip on hangar-talk', () => {
  assert.equal(validFacePackSize(1152, 768), true)
  assert.equal(validFacePackSize(1152, 128), false)
  assert.deepEqual(facePackCell(2, 3, 1152, 768), { sx: 256, sy: 384, sw: 128, sh: 128 })
  const mascot = talkingMascot('subject_1', 'subject_1', [0, 0, 0], 'tv')
  assert.equal(mascot.sourceUrl, '/examples/tv-head-humanoid.glb')
  assert.ok(mascot.speech?.facePack?.url.endsWith('tv-pack.png'))
  const doc = applyScene3DTemplate('hangar-talk')
  assert.equal(doc.slots.length, 2)
  assert.equal(doc.slots[0].speech?.facePack?.url, '/examples/face-pack/tv-pack.png')
  assert.equal(doc.slots[1].speech?.facePack?.url, '/examples/face-pack/skull-pack.png')
  assert.equal(doc.soundtrack?.[0]?.audio.url, '/examples/face-pack/neutral-vowels.wav')
  const parsed = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
  assert.deepEqual(parsed?.slots.map(slot => slot.speech?.facePack?.url), doc.slots.map(slot => slot.speech?.facePack?.url))
  assert.deepEqual(parsed?.slots.map(slot => slot.speech?.expressionCues), doc.slots.map(slot => slot.speech?.expressionCues))
  assert.equal(expressionAt(doc.slots[0].speech!, 1), 'happy')
  assert.equal(expressionAt(doc.slots[0].speech!, 2.7), 'happy')
  assert.equal(mouthAt(doc.slots[0].speech!, 2.7).b, VISEMES.indexOf('O'))
  assert.equal(expressionAt(doc.slots[1].speech!, 5), 'angry')
  assert.equal(expressionAt(doc.slots[1].speech!, 6.7), 'angry')
  assert.equal(mouthAt(doc.slots[1].speech!, 6.7).b, VISEMES.indexOf('O'))
  assert.equal(mouthAt(doc.slots[0].speech!, 0.5).b, 2)
  assert.equal(FACE_PACK_IDS.length, 20)
  const voxel = applyScene3DTemplate('voxel-talk')
  assert.equal(voxel.slots[0].speech?.facePack?.url, '/examples/face-pack/voxel-pack.png')
  assert.equal(voxel.slots[1].speech?.facePack?.url, '/examples/face-pack/cubeskull-pack.png')
})
test('face pack attach failures stay on the runtime so live thumbs and export cannot crash', () => {
  const hangar = applyScene3DTemplate('hangar-talk')
  const mascot = hangar.slots[0]
  const runtime = new FacePackRuntime()
  assert.doesNotThrow(() => runtime.sync(new Object3D(), mascot.speech, mascot.screen, 0.5))
  assert.equal(runtime.ready, false)
  assert.equal(runtime.error?.message, FACE_PACK_SCREEN_ERROR)
  const missingScreen = new FacePackRuntime()
  assert.doesNotThrow(() => missingScreen.sync(new Object3D(), mascot.speech, undefined, 0.5))
  assert.equal(missingScreen.error?.message, FACE_PACK_SCREEN_ERROR)
  const world = { dressingReady: true, slots: new Map() }
  assert.throws(() => worldAssetsReady(world, [{ ...mascot, screen: undefined }]), new RegExp(FACE_PACK_SCREEN_ERROR))
  const remounted = remountScene3DTemplate('two-shot', hangar, true)
  assert.equal(remounted.slots[0].speech?.facePack?.url, mascot.speech?.facePack?.url)
  assert.equal(remounted.slots[0].screen?.sourceUrl, mascot.screen?.sourceUrl)
  assert.equal(remounted.slots[0].screen?.anchor, mascot.screen?.anchor)
})
