import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseScene3DDocument } from '../src/features/scene3d/document'
import { applyScene3DTemplate, SCENE3D_TEMPLATES } from '../src/features/scene3d/templates'
import { parseMediaScreen } from '../src/features/scene3d/mediaScreen'
import { paletteAt, PIXEL_PALETTES } from '../src/features/scene3d/pixel/pixelPalettes'
import { parsePixelWorld } from '../src/features/scene3d/pixel/pixelWorld'
import { INDEX, paintRange, paintSky, ridge } from '../src/features/scene3d/pixel/pixelPaint'
import { meteorsAt, writePalette } from '../src/features/scene3d/pixel/pixelWorldSet'
import { addTv, applyScreenToAllTvs } from '../src/features/scene3d/pixel/pixelEdits'
import { PIXEL_TEMPLATE_IDS } from '../src/features/scene3d/pixel/pixelTemplateIds'

test('pixel lighting survives save and reopen, and bad values are bounded', () => {
  for (const id of PIXEL_TEMPLATE_IDS) {
    const doc = applyScene3DTemplate(id)
    const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))!
    assert.deepEqual(reopened.pixelWorld, doc.pixelWorld, id)
    assert.equal(reopened.dressing, doc.dressing)
    assert.ok(SCENE3D_TEMPLATES.some(template => template.id === id && template.tags?.includes('pixel')))
  }
  const parsed = parsePixelWorld({ palettes: ['aurora', 'nope'], hold: -4, pixelSize: 99, levels: 1, dither: 5, screenGlow: NaN })!
  assert.deepEqual(parsed.palettes, ['aurora'])
  assert.equal(parsed.hold, .5); assert.equal(parsed.pixelSize, 8); assert.equal(parsed.levels, 4); assert.equal(parsed.dither, 1); assert.equal(parsed.screenGlow, 1)
  assert.equal(parsePixelWorld('lake'), undefined)
  assert.equal('pixelWorld' in parseScene3DDocument(JSON.parse(JSON.stringify({ ...applyScene3DTemplate('two-shot') })))!, false)
})

test('a lighting program holds each mood, then glides into the next and loops', () => {
  const program = ['midnight', 'dawn'] as const
  assert.deepEqual(paletteAt(program, 10, 1), PIXEL_PALETTES.midnight)
  assert.deepEqual(paletteAt(program, 10, 11), PIXEL_PALETTES.dawn)
  const between = paletteAt(program, 10, 7)
  assert.notDeepEqual(between.sky, PIXEL_PALETTES.midnight.sky)
  assert.notDeepEqual(between.sky, PIXEL_PALETTES.dawn.sky)
  assert.deepEqual(paletteAt(program, 10, 21), PIXEL_PALETTES.midnight, 'loops back to the first mood')
})

test('stars twinkle by cycling their palette slots, not by repainting', () => {
  const a = new Uint8Array(1024), b = new Uint8Array(1024)
  writePalette(a, PIXEL_PALETTES.midnight, 0); writePalette(b, PIXEL_PALETTES.midnight, 1.3)
  const star = (bytes: Uint8Array) => Array.from(bytes.subarray(INDEX.star * 4, (INDEX.star + INDEX.starSteps) * 4))
  const sky = (bytes: Uint8Array) => Array.from(bytes.subarray(INDEX.sky * 4, (INDEX.sky + INDEX.skySteps) * 4))
  assert.notDeepEqual(star(a), star(b))
  assert.deepEqual(sky(a), sky(b))
})

test('the painted world is deterministic and keeps ridges inside the layer', () => {
  assert.deepEqual(paintSky(200, 80, { seed: 3, horizonRow: 70, stars: 40, moon: { x: .5, y: .5, radius: 6 } }).data,
    paintSky(200, 80, { seed: 3, horizonRow: 70, stars: 40, moon: { x: .5, y: .5, radius: 6 } }).data)
  const top = ridge(9, 300, 40, 20, 3, 25)
  assert.ok(top.every(row => row >= 2 && row < 80))
  assert.ok(Math.max(...top) - Math.min(...top) > 15, 'real peaks, not a flat line')
  const range = paintRange(300, 80, { seed: 9, base: 40, rough: 12, peaks: 3, peakLift: 25, body: INDEX.far, rim: INDEX.farRim, lightFrom: .5 })
  assert.equal(range.data[0], 0, 'sky above the ridge stays transparent')
  assert.equal(range.data[range.data.length - 1], INDEX.far)
})

test('shooting stars follow a seeded schedule, fall downwards and fade', () => {
  assert.deepEqual(meteorsAt(12.3, .8, [700, 214]).map(v => v.toArray()), meteorsAt(12.3, .8, [700, 214]).map(v => v.toArray()))
  assert.ok(meteorsAt(5, 0, [700, 214]).every(v => v.w === 0))
  let seen = 0
  for (let t = 0; t < 60; t += .25) for (const m of meteorsAt(t, 1, [700, 214])) if (m.w > 0) { seen++; assert.ok(Math.sin(m.z) > 0, 'heading down the sky') }
  assert.ok(seen > 10)
})

test('TVs: CRT screens keep their tube colour, share one recording and can be added', () => {
  const screen = parseMediaScreen({ sourceUrl: '/examples/a.mp4', media: 'video', style: 'crt', hue: 400 })!
  assert.equal(screen.style, 'crt'); assert.equal(screen.hue, 180)
  const wall = applyScene3DTemplate('pixel-tv-wall')
  const tvs = wall.slots.filter(slot => slot.screen?.style === 'crt')
  assert.ok(tvs.length >= 20)
  const chosen = { ...wall, slots: wall.slots.map((slot, i) => i === 0 ? { ...slot, screen: { ...slot.screen!, sourceUrl: '/api/v1/file/mine.mp4?workspace=w' } } : slot) }
  const shared = applyScreenToAllTvs(chosen, tvs[0].id)
  assert.ok(shared.slots.every(slot => slot.screen?.sourceUrl === '/api/v1/file/mine.mp4?workspace=w'))
  assert.deepEqual(shared.slots.map(slot => slot.screen?.hue), chosen.slots.map(slot => slot.screen?.hue))
  const more = addTv(shared)
  assert.equal(more.slots.length, shared.slots.length + 1)
  assert.equal(more.slots.at(-1)!.screen!.sourceUrl, '/api/v1/file/mine.mp4?workspace=w')
  assert.equal(new Set(more.slots.map(slot => slot.id)).size, more.slots.length)
})

test('adding TVs stops at 64 slots so the scene still saves and reopens', () => {
  const wall = applyScene3DTemplate('pixel-tv-wall')
  assert.ok(wall.slots.length < 64)
  let scene = wall
  for (let i = wall.slots.length; i < 70; i++) scene = addTv(scene)
  assert.equal(scene.slots.length, 64)
  assert.equal(addTv(scene), scene)
  assert.ok(parseScene3DDocument(JSON.parse(JSON.stringify(scene))))
  const overflow = { ...scene, slots: [...scene.slots, { ...scene.slots[0], id: 'overflow-tv' }] }
  assert.equal(parseScene3DDocument(JSON.parse(JSON.stringify(overflow))), null)
})
