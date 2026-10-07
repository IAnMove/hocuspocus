import assert from 'node:assert/strict'
import test from 'node:test'
import { loopPosition, loopSeconds, seamStart, wavSampleRate } from '../src/features/game-assets/audioLoop.ts'
import {
  approvableClean, atlasFrames, attemptWarnings, loopSamples, metricLines, musicFile, playbackSources, reviewAssets, stepFrame,
} from '../src/features/game-assets/reviewModel.ts'
import type { GameAsset, GameAttempt, GameWarning } from '../src/features/game-assets/types.ts'

function attempt(id: string, warnings: GameWarning[] = [], patch: Partial<GameAttempt> = {}): GameAttempt {
  return { id, status: 'ok', files: {}, warnings, ...patch }
}

function asset(id: string, attempts: GameAttempt[], status = 'review'): GameAsset {
  return {
    id, kind: 'character', name: id, description: '', status, tags: [], spec: {}, dependsOn: [],
    candidates: attempts.length, locked: false, attempts, approvedAttemptId: null,
  }
}

/** A 44-byte PCM WAV header for ``rate``. */
function wavHeader(rate: number): ArrayBuffer {
  const view = new DataView(new ArrayBuffer(44))
  const put = (offset: number, text: string) => [...text].forEach((char, index) => view.setUint8(offset + index, char.charCodeAt(0)))
  put(0, 'RIFF'); view.setUint32(4, 36, true); put(8, 'WAVE')
  put(12, 'LIST'); view.setUint32(16, 0, true) // an empty chunk before fmt
  put(20, 'fmt '); view.setUint32(24, 16, true); view.setUint16(28, 1, true); view.setUint16(30, 1, true); view.setUint32(32, rate, true)
  return view.buffer
}

test('atlas frames advance on their duration and then loop', () => {
  const frames = atlasFrames({
    frames: {
      b: { frame: { x: 8, y: 0, w: 8, h: 8 }, duration: 80 },
      a: { frame: { x: 0, y: 0, w: 8, h: 8 }, duration: 80 },
    },
  })
  assert.deepEqual(frames.map(frame => frame.name), ['a', 'b'])
  assert.equal(stepFrame(0, frames.length, true), 1)
  assert.equal(stepFrame(1, frames.length, true), 0)
  assert.equal(stepFrame(1, frames.length, false), 1)
})

test('bulk approve skips warnings, decided assets and assets with several undecided candidates', () => {
  const picks = approvableClean([
    asset('clean', [attempt('clean-a')]),
    asset('warned', [attempt('warned-a', ['loop_seam'])]),
    asset('held', [attempt('held-a')], 'approved'),
    asset('choice', [attempt('choice-a1'), attempt('choice-a2')]),
    asset('failed-first', [attempt('ff-a1', [], { status: 'failed' }), attempt('ff-a2')]),
    asset('second-chance', [attempt('sc-a1', [], { decision: 'rejected', note: 'no' }), attempt('sc-a2')], 'rejected'),
  ])
  assert.deepEqual(picks, [
    { assetId: 'clean', attemptId: 'clean-a' },
    { assetId: 'failed-first', attemptId: 'ff-a2' },
    { assetId: 'second-chance', attemptId: 'sc-a2' },
  ])
})

test('review lists rejected assets that still have an undecided ok candidate', () => {
  const assets = [
    asset('open', [attempt('o-a1', [], { decision: 'rejected', note: 'x' }), attempt('o-a2')], 'rejected'),
    asset('done', [attempt('d-a1', [], { decision: 'rejected', note: 'x' })], 'rejected'),
    asset('broken', [attempt('b-a1', [], { status: 'failed' })], 'rejected'),
    asset('waiting', [attempt('w-a1')]),
  ]
  assert.deepEqual(reviewAssets(assets, '').map(item => item.id), ['open', 'waiting'])
  assert.deepEqual(reviewAssets(assets, 'music'), [])
})

test('warnings read strings and objects with stable keys and a code', () => {
  const warnings = attemptWarnings(attempt('a', [
    'loop_seam',
    'duplicate_of:heroe',
    { code: 'seam_visible', message: 'seam error 2.1 is above 1.5', file: 'tile-2.png' },
    { message: 'only text' },
    'ffmpeg unavailable; wrote WAV instead',
  ]))
  assert.deepEqual(warnings.map(item => item.code), ['loop_seam', 'duplicate_of', 'seam_visible', '', 'ffmpeg unavailable; wrote WAV instead'])
  assert.equal(warnings[1].ref, 'heroe')
  assert.equal(warnings[2].file, 'tile-2.png')
  assert.equal(new Set(warnings.map(item => item.key)).size, warnings.length)
  assert.ok(warnings.every(item => !String(item.message).includes('[object')))
})

test('metric lines keep loop points and missing clips first and hide candidate lists', () => {
  const metrics: Record<string, unknown> = {
    a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7, h: 8, i: 9, j: 10, k: 11,
    loopStart: 0, loopEnd: 95999, missingClips: ['run', 'jump'], attemptIds: ['x'], candidates: [{ id: 'x' }],
  }
  const lines = metricLines(metrics)
  assert.deepEqual(lines.slice(0, 3), ['loopStart: 0', 'loopEnd: 95999', 'missingClips: run, jump'])
  assert.equal(lines.length, 10)
  assert.ok(!lines.some(line => line.startsWith('attemptIds') || line.startsWith('candidates')))
  assert.ok(!metricLines({ missingClips: [] }).length)
})

test('loop points are sample indices with an inclusive end, at the file rate', () => {
  assert.equal(wavSampleRate(wavHeader(44100)), 44100)
  assert.equal(wavSampleRate(new ArrayBuffer(8)), 0)
  assert.deepEqual(loopSamples({ loopStart: 0, loopEnd: 44099 }), { start: 0, end: 44099 })
  assert.equal(loopSamples({ duration: 3 }), null)
  const loop = loopSeconds({ start: 0, end: 44099 }, 44100, 2)
  assert.deepEqual(loop, { start: 0, end: 1 })
  assert.deepEqual(loopSeconds(null, 44100, 2), { start: 0, end: 2 })
  assert.equal(seamStart({ start: 0, end: 60 }), 58)
  assert.equal(seamStart({ start: 0, end: 1 }), 0)
  assert.deepEqual(loopPosition(0, 0.5, loop), { position: 0.5, turns: 0 })
  assert.deepEqual(loopPosition(0, 2.25, loop), { position: 0.25, turns: 2 })
})

test('numbered files are the sfx variants; music loops the WAV', () => {
  assert.deepEqual(playbackSources({ '2': 'b.wav', '1': 'a.wav' }).map(item => item.key), ['1', '2'])
  assert.equal(playbackSources({ wav: 'a.wav', ogg: 'a.ogg' })[0].key, 'ogg')
  assert.equal(musicFile({ wav: 'a.wav', ogg: 'a.ogg' }), 'a.wav')
  assert.equal(musicFile({ ogg: 'a.ogg' }), 'a.ogg')
})
