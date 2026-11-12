import assert from 'node:assert/strict'
import test from 'node:test'
import type { MontageDocument } from '../src/api/montages.ts'
import { editorFromMontage, exportLayerFields, montageFromEditor, persistOpenMontage, playableUrl, resolutionFor } from '../src/features/video-editor/montage.ts'

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

test('editor saves keep takes, lyric and notes of each clip', () => {
  const withTakes: MontageDocument = { ...montage, notes: 'rebuilt', clips: [{ ...montage.clips[0], lyric: 'fly', takes: [{ id: 't1', source: 'alt.mp4' }, { id: 't2', pending: { jobId: 'j' } }] }] }
  const saved = montageFromEditor({ projectName: 'Bird', resolution: resolutionFor(1920, 1080), fps: 24,
    clips: [{ id: 'c1', name: 'shot', source: 'shot.mp4', trimStart: 1, trimEnd: 5, volume: 1, muted: false, fit: 'fill', transition: 'crossfade',
      transitionDuration: 0.4, transitionText: '', transitionTextSize: 100 } as never],
    soundtrack: null, layers: { overlays: [], audioCues: [], duck: 0 }, origins: {},
    extras: { c1: { takes: withTakes.clips[0].takes, lyric: 'fly' } }, notes: withTakes.notes })
  assert.equal(saved.clips[0].takes?.length, 2)
  assert.equal(saved.clips[0].lyric, 'fly')
  assert.equal(saved.notes, 'rebuilt')
  assert.equal('comic' in saved.clips[0], false)
})

test('a lyric and a comic choice survive save and reload', async () => {
  const probe = async () => ({ duration: 5, width: 1080, height: 1920, fps: 24, has_audio: false, pixel_format: 'yuv420p', has_alpha: false })
  const withLine = { ...montage, width: 1080, height: 1920, clips: [{ ...montage.clips[0], lyric: ' fly / high ', comic: { frame: 1.25, text: 'bubble' as const } }] }
  const opened = await editorFromMontage(withLine, probe, async () => ({ duration: 1 }), () => 'thumb')
  assert.equal(opened.extras.c1.lyric, ' fly / high ')
  assert.deepEqual(opened.extras.c1.comic, { frame: 1.25, text: 'bubble' })
  const saved = montageFromEditor({ projectName: 'Bird', resolution: resolutionFor(1080, 1920), fps: 24, clips: opened.clips,
    soundtrack: null, layers: { overlays: [], audioCues: [], duck: 0 }, origins: opened.origins, extras: opened.extras })
  assert.equal(saved.clips[0].lyric, ' fly / high ')
  assert.deepEqual(saved.clips[0].comic, { frame: 1.25, text: 'bubble' })
  const again = await editorFromMontage(saved, probe, async () => ({ duration: 1 }), () => 'thumb')
  assert.deepEqual(again.extras.c1, opened.extras.c1)
  const plain = await editorFromMontage(montage, probe, async () => ({ duration: 171 }), source => `thumb:${source}`)
  assert.equal(plain.extras.c1, undefined)
})

test('persistOpenMontage writes the editor order onto the open file', async () => {
  const seen: Array<{ file?: string; ids: string[] }> = []
  const ref = await persistOpenMontage({
    workspace: 'studio',
    state: {
      projectName: 'Bird',
      resolution: resolutionFor(1920, 1080),
      fps: 24,
      clips: [
        { id: 'b', name: 'second', source: 'b.mp4', trimStart: 0, trimEnd: 2, volume: 1, muted: false, fit: 'fit', transition: 'none', transitionDuration: 0.5, transitionText: '', transitionTextSize: 100 } as never,
        { id: 'a', name: 'first', source: 'a.mp4', trimStart: 0, trimEnd: 3, volume: 1, muted: false, fit: 'fit', transition: 'none', transitionDuration: 0.5, transitionText: '', transitionTextSize: 100 } as never,
      ],
      soundtrack: null,
    },
    layers: { overlays: [], audioCues: [], duck: 0 },
    ref: { file: 'song.montage.json', revision: 4, origins: {}, extras: { b: { lyric: 'keep' } } },
  }, async payload => {
    seen.push({ file: payload.file, ids: payload.montage.clips.map(clip => clip.id) })
    assert.equal(payload.workspace, 'studio')
    assert.equal(payload.expected_revision, 4)
    assert.equal(payload.montage.clips[0].lyric, 'keep')
    return { file: 'song.montage.json', revision: 5, url: '/song.montage.json' }
  })
  assert.deepEqual(seen, [{ file: 'song.montage.json', ids: ['b', 'a'] }])
  assert.equal(ref.revision, 5)
  assert.equal(ref.file, 'song.montage.json')
})

test('a bare montage source plays from the workspace; URLs and paths stay as they are', () => {
  assert.equal(playableUrl('ol-o01.mp4', 'orcos libres'), '/api/v1/file/ol-o01.mp4?workspace=orcos%20libres')
  assert.equal(playableUrl('/api/v1/file/a.mp4?workspace=w', 'w'), '/api/v1/file/a.mp4?workspace=w')
  assert.equal(playableUrl('https://x/a.mp4', 'w'), 'https://x/a.mp4')
  assert.equal(playableUrl('a.mp4', ''), 'a.mp4')
})
