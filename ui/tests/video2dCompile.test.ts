import assert from 'node:assert/strict'
import test from 'node:test'
import { compilePayload } from '../scripts/video2dCompile.ts'

const ASSETS = { hero: '/api/v1/file/hero.png', plate: '/api/v1/file/plate.png' }

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
  assert.equal(layers.hero?.source, '/examples/hero.png')
  assert.equal(layers.plate?.source, '/examples/plate.png')
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
  assert.deepEqual(result.result.document.layers.map(layer => layer.id), ['plate', 'hero', 'camera', 'atmosphere-dust'])
  assert.deepEqual(result.result.warnings, [])
})

test('a video2d candidate keeps slot images and the catalog duration', () => {
  const result = compilePayload({
    operation: 'scenes.template.compile',
    input: { templateId: 'documentary-history', assets: ASSETS, controls: { duration: 4 } },
  })
  assert.equal(result.ok, true)
  if (!result.ok || !('document' in result.result)) return
  const layers = Object.fromEntries(result.result.document.layers.map(layer => [layer.id, layer]))
  assert.equal(result.result.document.duration, 4)
  assert.equal(layers.hero?.source, ASSETS.hero)
  assert.equal(layers.plate?.source, ASSETS.plate)
  assert.equal(layers.plate?.type, 'image')
  assert.equal(layers['atmosphere-plate']?.type, 'effect')
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
