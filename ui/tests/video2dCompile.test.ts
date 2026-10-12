import assert from 'node:assert/strict'
import test from 'node:test'
import { compilePayload, slotType } from '../scripts/video2dCompile.ts'

const ASSETS = { subject_1: '/api/v1/file/hero.png', background: '/api/v1/file/plate.png' }
const OLD_NAMES = { hero: '/api/v1/file/hero.png', plate: '/api/v1/file/plate.png' }
const compile = (input: Record<string, unknown>) => compilePayload({ operation: 'scenes.template.compile', input })

test('bundled example URLs compile on a regular template', () => {
  const result = compilePayload({
    operation: 'scenes.template.compile',
    input: {
      templateId: 'cinema-establishing',
      assets: { hero: '/examples/hero.png', plate: '/examples/plate.png' },
    },
  })
  assert.equal(result.ok, true)
  if (!result.ok || !('document' in result.result)) return
  const layers = Object.fromEntries(result.result.document.layers.map(layer => [layer.id, layer]))
  assert.equal(layers.subject_1?.source, '/examples/hero.png')
  assert.equal(layers.background?.source, '/examples/plate.png')
})

test('a known scene template compiles to the builder layer ids', () => {
  const result = compilePayload({
    operation: 'scenes.template.compile',
    input: { templateId: 'cinema-establishing', assets: ASSETS },
  })
  assert.equal(result.ok, true)
  if (!result.ok) return
  assert.ok('document' in result.result)
  if (!('document' in result.result)) return
  assert.equal(result.result.document.name, 'Plano de establecimiento · candidata')
  assert.deepEqual(result.result.document.layers.map(layer => layer.id), ['background', 'subject_1', 'camera', 'atmosphere-dust'])
  assert.deepEqual(result.result.warnings, [])
})

test('a titled card keeps its slot images (old names too) and the requested duration', () => {
  const result = compilePayload({
    operation: 'scenes.template.compile',
    input: { templateId: 'documentary-history', assets: OLD_NAMES, controls: { duration: 4 } },
  })
  assert.equal(result.ok, true)
  if (!result.ok || !('document' in result.result)) return
  const layers = Object.fromEntries(result.result.document.layers.map(layer => [layer.id, layer]))
  assert.equal(result.result.document.duration, 4)
  assert.equal(layers.subject_1?.source, OLD_NAMES.hero)
  assert.equal(layers.background?.source, OLD_NAMES.plate)
  assert.equal(layers.background?.type, 'image')
  assert.equal(layers['atmosphere-dust']?.type, 'effect')
})

test('a 9:16 compile keeps title y inside the vertical safe area', () => {
  const result = compilePayload({
    operation: 'scenes.template.compile',
    input: { templateId: 'documentary-history', assets: ASSETS, width: 1080, height: 1920 },
  })
  assert.equal(result.ok, true)
  if (!result.ok || !('document' in result.result)) return
  const scene = result.result.document
  assert.equal(scene.width, 1080)
  assert.equal(scene.height, 1920)
  assert.ok(scene.height > scene.width)
  const texts = scene.texts ?? []
  assert.ok(texts.length > 0)
  assert.deepEqual(Object.fromEntries(texts.map(cue => [cue.id, cue.y])), { date: 64, caption: 72, count: 42, label: 62 })
  for (const cue of texts) {
    assert.ok(cue.y >= 12 && cue.y <= 80, cue.id)
    assert.ok(cue.maxWidth == null || cue.maxWidth <= 90, cue.id)
  }
  assert.deepEqual(result.result.warnings, [])
})

test('portrait text templates stay inside the vertical safe area', () => {
  const samples: Record<string, Record<string, string>> = {
    'lower-third-date': { date: '1968', caption: 'Harbour' },
    'chorus-banner': { line: 'Salt' },
    'title-card': { title: 'Musktopia', subtitle: 'Harbour' },
    'end-card': { title: 'Soon', cta: '@studio' },
    'year-counter': { from: '1960', to: '1968', label: 'Year' },
    quote: { quote: 'Keep the line.', author: 'Ada' },
    'trailer-slam': { lines: 'ONE|LAST' },
    chapter: { kicker: 'Chapter', title: 'One' },
    'social-caption': { caption: 'Salt on the windows' },
  }
  for (const [templateId, fields] of Object.entries(samples)) {
    const result = compilePayload({
      operation: 'scenes.text.template',
      input: { templateId, fields, width: 1080, height: 1920, start: 0, duration: 4 },
    })
    assert.equal(result.ok, true, templateId)
    if (!result.ok || !('texts' in result.result)) continue
    assert.ok(result.result.texts.length > 0, templateId)
    for (const cue of result.result.texts) {
      assert.equal(cue.template, templateId)
      assert.ok(cue.y >= 12 && cue.y <= 80, `${templateId}:${cue.id}`)
      assert.ok(cue.maxWidth == null || cue.maxWidth <= 90, `${templateId}:${cue.id}`)
    }
  }
})

test('a bad lyrics string returns a stable error and does not throw', () => {
  const bad = compilePayload({ operation: 'scenes.lyrics.import', input: { format: 'srt', text: 'this is not a subtitle' } })
  assert.equal(bad.ok, false)
  if (bad.ok) return
  assert.equal(bad.code, 'lyrics_bad_file')
  const broken = compilePayload({ operation: 'scenes.lyrics.import', input: { format: 'timing-bundle', text: '{' } })
  assert.equal(broken.ok, false)
  if (!broken.ok) assert.equal(broken.code, 'lyrics_bad_file')
  const good = compilePayload({
    operation: 'scenes.lyrics.import',
    input: { format: 'srt', text: '1\n00:00:01,000 --> 00:00:03,000\nHola mundo\n' },
  })
  assert.equal(good.ok, true)
  if (good.ok && 'lyrics' in good.result) {
    assert.equal(good.result.lyrics.mode, 'karaoke')
    assert.equal(good.result.lyrics.source?.kind, 'srt')
    assert.equal(good.result.lyrics.lines[0]?.words.length, 2)
    assert.ok(good.result.lyrics.style.y >= 12 && good.result.lyrics.style.y <= 80)
    assert.ok(good.result.lyrics.style.maxWidth <= 90)
  }
})

test('an alias compiles as its card with its preset and records the alias', () => {
  const result = compile({ templateId: 'music-stage', assets: OLD_NAMES })
  assert.equal(result.ok, true)
  if (!result.ok || !('document' in result.result)) return
  const narrative = result.result.document.narrative
  assert.equal(narrative?.templateId, 'music-pulse')
  assert.equal(narrative?.controls.alias, 'music-stage')
  assert.equal(narrative?.controls.camera, 'sweep')
})

test('retired ids, slot conflicts and bad choices fail with the shared codes', () => {
  const retired = compile({ templateId: 'lyric-vertical', assets: ASSETS })
  assert.deepEqual(retired.ok ? undefined : [retired.code, retired.use_instead], ['template_retired', ['scenes.lyrics.import']])
  const conflict = compile({ templateId: 'cinema-establishing', assets: { ...ASSETS, hero: ASSETS.subject_1 } })
  assert.equal(conflict.ok ? 'compiled' : conflict.code, 'slot_alias_conflict')
  const choice = compile({ templateId: 'music-pulse', assets: ASSETS, controls: { camera: 'dolly' } })
  assert.equal(choice.ok ? 'compiled' : choice.code, 'template_bad_control')
  const shape = compile({ templateId: 'music-pulse', assets: ASSETS, controls: { camera: ['push'] } })
  assert.equal(shape.ok ? 'compiled' : shape.code, 'template_bad_control')
  const missing = compile({ templateId: 'music-pinball', assets: ASSETS, controls: { bouncer: 'prop' } })
  assert.equal(missing.ok ? 'compiled' : missing.code, 'template_missing_slot')
})

test('a looping video is a background, never a cutout', () => {
  assert.equal(slotType('/api/v1/file/loop.mp4?workspace=a', ['image', 'video']), 'video')
  assert.equal(slotType('/api/v1/file/loop.webm', ['image', 'video']), 'video')
  assert.equal(slotType('/api/v1/file/ship.glb', ['image', 'model3d']), 'model3d')
  assert.equal(slotType('/api/v1/assets/abc/file', ['image', 'video']), 'image')
  const result = compile({ templateId: 'music-speed-flight', assets: { subject_1: ASSETS.subject_1, background: '/api/v1/file/sea.mp4' } })
  assert.equal(result.ok, true)
  if (!result.ok || !('document' in result.result)) return
  const ids = result.result.document.layers.map(layer => layer.id)
  assert.deepEqual(ids, ['background', 'subject_1', 'atmosphere-speedlines', 'camera'], 'a video already moves: no strip copy')
  assert.equal(result.result.document.layers[0].type, 'video')
  const cutout = compile({ templateId: 'music-speed-flight', assets: { subject_1: '/api/v1/file/dance.mp4', background: ASSETS.background } })
  assert.equal(cutout.ok ? 'compiled' : cutout.code, 'template_bad_asset')
})
