import assert from 'node:assert/strict'
import test from 'node:test'
import { editorPreflight, type PreflightClip } from '../src/features/video-editor/editorPreflight.ts'

function clip(patch: Partial<PreflightClip> = {}): PreflightClip {
  return {
    id: 'a', fps: 30, width: 1280, height: 720, volume: 1, muted: false, hasAudio: true,
    trimStart: 0, trimEnd: 4, transition: 'none', transitionDuration: 0, ...patch,
  }
}

test('a continuous timeline at one frame rate stays quiet', () => {
  assert.deepEqual(editorPreflight({ clips: [clip()], soundtrack: null }), [])
})

test('an empty timeline, a short soundtrack, mixed sources and a hot fader warn', () => {
  assert.deepEqual(editorPreflight({ clips: [], soundtrack: null }), [{ code: 'timeline_gap', t: 0 }])
  const gap = editorPreflight({
    clips: [clip()],
    soundtrack: { volume: 1, trimStart: 0, trimEnd: 1, loop: false },
  })
  assert.equal(gap[0]?.code, 'timeline_gap')
  assert.equal(gap[0]?.t, 1)
  assert.deepEqual(editorPreflight({
    clips: [clip()],
    soundtrack: { volume: 1, trimStart: 0, trimEnd: 1, loop: true },
  }), [])
  const mixed = editorPreflight({
    clips: [clip({ id: 'a' }), clip({ id: 'b', fps: 24, width: 1920, height: 1080, trimStart: 0, trimEnd: 2 })],
    soundtrack: null,
  })
  assert.deepEqual(mixed.map(item => item.code), ['mixed_fps', 'mixed_resolution'])
  const hot = editorPreflight({
    clips: [clip()],
    soundtrack: { volume: 1.4, trimStart: 0, trimEnd: 4, loop: false },
  })
  assert.equal(hot.some(item => item.code === 'mix_hot'), true)
})
