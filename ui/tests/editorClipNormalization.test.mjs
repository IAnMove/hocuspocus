import assert from 'node:assert/strict'
import test from 'node:test'
import {
  editorClipRecoveryMessage,
  normalizeEditorClips,
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
