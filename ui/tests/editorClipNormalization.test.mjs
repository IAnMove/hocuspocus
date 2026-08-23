import assert from 'node:assert/strict'
import test from 'node:test'
import {
  applyTransitionToGaps,
  editorClipRecoveryMessage,
  normalizeEditorClips,
  splitClipAtTime,
  trimClipFromDelta,
} from '../src/features/video-editor/editorClipNormalization.ts'

function validClip(overrides = {}) {
  return {
    id: 'clip-valid', name: 'Valid clip', source: 'valid.mp4', previewUrl: 'valid.mp4',
    thumbnailUrl: 'valid.jpg', duration: 10, width: 1920, height: 1080, fps: 30,
    has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
    trimStart: 1, trimEnd: 9, volume: 0.8, muted: false, fit: 'fill',
    transition: 'crossfade', transitionDuration: 0.7,
    transitionText: 'Later', transitionTextSize: 90,
    ...overrides,
  }
}

function normalize(values) {
  let id = 0
  return normalizeEditorClips(values, {
    idFactory: () => `clip-recovered-${++id}`,
    thumbnailUrl: source => `thumbnail:${source}`,
  })
}

test('valid editor clips survive normalization byte-for-field', () => {
  const input = validClip()
  const result = normalize([input])
  assert.deepEqual(result.clips, [input])
  assert.equal(result.repairedCount, 0)
  assert.equal(result.discardedCount, 0)
  assert.equal(editorClipRecoveryMessage(result), null)
})

test('corrupt numeric fields, enums, duplicate ids and inverted trims are repaired deterministically', () => {
  const result = normalize([
    validClip({
      id: '', name: '', source: '  repaired.mp4  ', previewUrl: '', thumbnailUrl: '',
      width: '1920', height: Number.NaN, fps: '60', trimStart: 9, trimEnd: 2,
      volume: 8, muted: 'yes', fit: 'stretch', transition: 'teleport',
      transitionDuration: Number.NaN, transitionText: 7, transitionTextSize: 'huge',
    }),
    validClip({ id: 'clip-recovered-1', source: 'duplicate.mp4', trimStart: '2', trimEnd: '8' }),
  ])

  assert.equal(result.discardedCount, 0)
  assert.equal(result.repairedCount, 2)
  assert.deepEqual(result.clips.map(clip => clip.id), ['clip-recovered-1', 'clip-recovered-2'])
  assert.deepEqual(
    result.clips.map(clip => [clip.trimStart, clip.trimEnd]),
    [[2, 9], [0, 10]],
  )
  assert.deepEqual(result.clips[0], {
    id: 'clip-recovered-1', name: 'repaired.mp4', source: 'repaired.mp4',
    previewUrl: 'repaired.mp4', thumbnailUrl: 'thumbnail:repaired.mp4',
    duration: 10, width: 0, height: 0, fps: 30,
    has_audio: true, pixel_format: 'yuv420p', has_alpha: false,
    trimStart: 2, trimEnd: 9,
    volume: 1, muted: false, fit: 'fit', transition: 'none',
    transitionDuration: 0.5, transitionText: 'Momentos después…', transitionTextSize: 100,
  })
  for (const clip of result.clips) {
    assert.ok(Number.isFinite(clip.trimStart))
    assert.ok(Number.isFinite(clip.trimEnd))
    assert.ok(clip.trimStart >= 0 && clip.trimStart < clip.trimEnd && clip.trimEnd <= clip.duration)
    assert.ok(clip.volume >= 0 && clip.volume <= 1)
  }
})

test('missing, string and non-finite durations are discarded with an explicit warning', () => {
  const result = normalize([
    validClip({ source: '' }),
    validClip({ source: 'missing-duration.mp4', duration: undefined }),
    validClip({ source: 'string-duration.mp4', duration: '10' }),
    validClip({ source: 'infinite-duration.mp4', duration: Number.POSITIVE_INFINITY }),
    validClip({ source: 'kept.mp4' }),
  ])

  assert.deepEqual(result.clips.map(clip => clip.source), ['kept.mp4'])
  assert.equal(result.discardedCount, 4)
  assert.match(editorClipRecoveryMessage(result) || '', /4 discarded because source or duration was invalid/)
})

test('splitClipAtTime cuts one clip into two at the playhead and refuses the edges', () => {
  const clip = validClip({ trimStart: 1, trimEnd: 9 })
  assert.equal(splitClipAtTime(clip, 1.02, 'clip-b'), null)
  assert.equal(splitClipAtTime(clip, 8.99, 'clip-b'), null)
  const parts = splitClipAtTime(clip, 4, 'clip-b')
  assert.ok(parts)
  assert.equal(parts[0].trimStart, 1)
  assert.equal(parts[0].trimEnd, 4)
  assert.equal(parts[0].transition, 'none')
  assert.equal(parts[1].id, 'clip-b')
  assert.equal(parts[1].trimStart, 4)
  assert.equal(parts[1].trimEnd, 9)
})

test('applyTransitionToGaps sets every join and leaves the last clip alone', () => {
  const clips = [
    validClip({ id: 'a', transition: 'none' }),
    validClip({ id: 'b', transition: 'wipe-left' }),
    validClip({ id: 'c', transition: 'crossfade' }),
  ]
  const next = applyTransitionToGaps(clips, 'fade-black')
  assert.equal(next[0].transition, 'fade-black')
  assert.equal(next[1].transition, 'fade-black')
  assert.equal(next[2].transition, 'crossfade')
})

test('timeline edge trim moves slowly and will not collapse a clip', () => {
  const clip = validClip({ trimStart: 2, trimEnd: 8, duration: 10 })
  const shorterStart = trimClipFromDelta(clip, 'start', 1)
  assert.equal(shorterStart.trimStart, 3)
  const collapsed = trimClipFromDelta(clip, 'end', -20)
  assert.equal(collapsed.trimEnd, 2.4)
  const extended = trimClipFromDelta(clip, 'end', 5)
  assert.equal(extended.trimEnd, 10)
})
