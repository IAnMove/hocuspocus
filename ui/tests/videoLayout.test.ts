import assert from 'node:assert/strict'
import test from 'node:test'
import { exportClipBody, normalizeEditorClips, type EditorClip } from '../src/features/video-editor/editorClipNormalization.ts'
import { clipObjectPosition, clipPreviewClass, focusPercent } from '../src/features/video-editor/clipFrame.ts'

const base = {
  id: 'c1',
  name: 'wide',
  source: 'wide.mp4',
  previewUrl: 'wide.mp4',
  thumbnailUrl: 'wide.jpg',
  duration: 4,
  width: 1920,
  height: 1080,
  fps: 24,
  has_audio: false,
  pixel_format: 'yuv420p',
  has_alpha: false,
  trimStart: 0,
  trimEnd: 4,
  volume: 1,
  muted: false,
  fit: 'fit' as const,
  transition: 'none',
  transitionDuration: 0.5,
  transitionText: '',
  transitionTextSize: 100,
}

test('editor clips keep blur and focus only when present', () => {
  const kept = normalizeEditorClips([{ ...base, fit: 'blur', focusX: 12, blurAmount: 0.8, focusY: 140 }], {
    idFactory: () => 'generated',
    thumbnailUrl: () => 'thumb',
  })
  const clip = kept.clips[0]
  assert.equal(clip.fit, 'blur')
  assert.equal(clip.focusX, 12)
  assert.equal(clip.focusY, 100)
  assert.equal(clip.blurAmount, 0.8)
  assert.equal(clip.backgroundDim, undefined)
  const plain = normalizeEditorClips([base], { idFactory: () => 'generated', thumbnailUrl: () => 'thumb' })
  assert.equal(plain.clips[0].fit, 'fit')
  assert.equal('focusX' in plain.clips[0], false)
  assert.equal(plain.repairedCount, 0)
})

test('export body and preview helpers follow the frame mode', () => {
  const clip = { ...base, fit: 'fill', focusX: 10, focusY: 80 } as EditorClip
  const body = exportClipBody(clip)
  assert.equal(body.fit, 'fill')
  assert.equal(body.focus_x, 10)
  assert.equal(body.focus_y, 80)
  assert.equal('blur_amount' in body, false)
  assert.equal(clipPreviewClass('fill').includes('object-cover'), true)
  assert.equal(clipPreviewClass('blur').includes('object-contain'), true)
  assert.equal(clipObjectPosition(clip), '10% 80%')
  assert.equal(clipObjectPosition({ fit: 'blur' }), undefined)
  assert.equal(focusPercent(0, 0, 200), 0)
  assert.equal(focusPercent(150, 0, 200), 75)
  assert.equal(focusPercent(999, 0, 100), 100)
})
