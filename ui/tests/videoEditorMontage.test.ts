import assert from 'node:assert/strict'
import test from 'node:test'
import type { MontageDocument } from '../src/api/montages.ts'
import { editorFromMontage, exportLayerFields, montageFromEditor, resolutionFor } from '../src/features/video-editor/montage.ts'

const montage: MontageDocument = {
  version: 1, name: 'Bird', width: 1920, height: 1080, fps: 24,
  clips: [{ id: 'c1', name: 'shot', source: 'shot.mp4', trimStart: 1, trimEnd: 0, volume: 1, muted: false, fit: 'fill',
    transition: 'crossfade', transitionDuration: 0.4, transitionText: '', transitionTextSize: 100, origin: { kind: 'scene2d', scene: 'intro.scene.json' } }],
  soundtrack: { name: 'song', source: 'song.wav', trimStart: 0, trimEnd: 0, volume: 1, loop: false },
  overlays: [{ id: 't1', name: 'title', source: 'cap.png', start: 0.5, end: 6, x: 50, y: 50, width: 100, opacity: 1, fadeIn: 1, fadeOut: 1 }],
  audioCues: [{ id: 'vo', name: 'vo', source: 'vo.wav', start: 0.8, volume: 1.6, trimStart: 0, trimEnd: 0 }],
  duck: 0.5,
}

test('opening a montage probes media and keeps provenance and layers', async () => {
  const opened = await editorFromMontage(
    montage,
    async () => ({ duration: 5, width: 1920, height: 1080, fps: 24, has_audio: false, pixel_format: 'yuv420p', has_alpha: false }),
    async () => ({ duration: 171 }),
    source => `thumb:${source}`,
  )
  assert.equal(opened.clips[0].trimEnd, 5)
  assert.equal(opened.clips[0].fit, 'fill')
  assert.equal(opened.clips[0].thumbnailUrl, 'thumb:shot.mp4')
  assert.equal(opened.soundtrack?.trimEnd, 171)
  assert.deepEqual(opened.origins.c1, { kind: 'scene2d', scene: 'intro.scene.json' })
  assert.equal(opened.layers.audioCues[0].volume, 1.6)

  const saved = montageFromEditor({ projectName: 'Bird', resolution: resolutionFor(1920, 1080), fps: 24, clips: opened.clips,
    soundtrack: opened.soundtrack, layers: opened.layers, origins: opened.origins })
  assert.equal(saved.clips[0].origin?.scene, 'intro.scene.json')
  assert.equal(saved.overlays.length, 1)
})

test('export fields are snake_case and omitted without layers', () => {
  assert.deepEqual(exportLayerFields({ overlays: [], audioCues: [], duck: 0 }), {})
  const fields = exportLayerFields({ overlays: montage.overlays, audioCues: montage.audioCues, duck: 0.5 })
  assert.equal(fields.overlays?.[0].fade_in, 1)
  assert.equal(fields.audio_cues?.[0].trim_end, 0)
  assert.equal(fields.duck, 0.5)
  assert.equal(resolutionFor(1080, 1920).label, 'Portrait 1080p · 9:16')
})
