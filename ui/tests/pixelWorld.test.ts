import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseScene3DDocument } from '../src/features/scene3d/document'
import { applyScene3DTemplate, SCENE3D_TEMPLATES } from '../src/features/scene3d/templates'
import { parseMediaScreen } from '../src/features/scene3d/mediaScreen'
import { paletteAt, PIXEL_PALETTES } from '../src/features/scene3d/pixel/pixelPalettes'
import { parsePixelWorld } from '../src/features/scene3d/pixel/pixelWorld'
import { INDEX, paintRange, paintSky, ridge } from '../src/features/scene3d/pixel/pixelPaint'
import { meteorsAt, writePalette } from '../src/features/scene3d/pixel/pixelCycle'
import { paintPixelWorld, pixelWorldGroup } from '../src/features/scene3d/pixel/pixelWorldSet'
import { bodyDirection, parsePixelScene, PIXEL_WORLD_KINDS, resolvePixelScene } from '../src/features/scene3d/pixel/pixelScene'
import { worldPlan } from '../src/features/scene3d/pixel/pixelWorlds'
import { flashPalette, paletteWith, parsePaletteOverrides, tintPalette } from '../src/features/scene3d/pixel/pixelPalettes'
import { Color, Group, Scene, Vector3 } from 'three'
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

test('every world paints its planes from a layout that can be reimagined', () => {
  for (const kind of PIXEL_WORLD_KINDS) {
    const scene = resolvePixelScene(kind, undefined)
    const plan = worldPlan(kind, scene)
    assert.ok(plan.layers.some(layer => layer.sky), kind)
    const sky = plan.layers.find(layer => layer.sky)!
    const first = sky.paint(...sky.texture).data
    assert.deepEqual(first, sky.paint(...sky.texture).data, `${kind} is deterministic`)
    const other = worldPlan(kind, { ...scene, seed: scene.seed + 1 }).layers.find(layer => layer.sky)!
    assert.notDeepEqual(first, other.paint(...other.texture).data, `${kind} reimagines with a new seed`)
  }
  const coast = worldPlan('pixel-coast', resolvePixelScene('pixel-coast', undefined)).layers.find(layer => layer.z === -28)!
  assert.ok(coast.paint(...coast.texture).lamp, 'the lighthouse reports its lamp for the beam')
  assert.equal(worldPlan('pixel-desert', resolvePixelScene('pixel-desert', undefined)).ground, 'sand')
})

test('scene changes are bounded, and moving the moon moves the light', () => {
  assert.deepEqual(parsePixelScene({ bodyX: 4, bodySize: 9, body: 'sun', seed: -3, junk: 1, meteorDirection: 'up' }), { bodyX: 1, bodySize: 2.5, body: 'sun', seed: 1 })
  assert.equal(parsePixelScene({}), undefined)
  const left = bodyDirection({ bodyX: .1, bodyY: .5 }), right = bodyDirection({ bodyX: .9, bodyY: .5 })
  assert.ok(left[0] < 0 && right[0] > 0)
  assert.ok(bodyDirection({ bodyX: .5, bodyY: .9 })[1] > bodyDirection({ bodyX: .5, bodyY: .1 })[1])
  const root = pixelWorldGroup('pixel-lake'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = { ...applyScene3DTemplate('pixel-moon-lake').pixelWorld!, scene: { bodyX: .1 } }
  paintPixelWorld(root, new Scene(), dir, pixel, 1, 720)
  assert.ok(dir.position.x < 0, 'the key light comes from the moon on the left')
  assert.ok((root as Group).children.length >= 4, 'the planes are painted on the first frame')
})

test('a mood can be recoloured and survives save and reopen', () => {
  const colors = parsePaletteOverrides({ midnight: { sky0: '#FF0000', moon: 'red', junk: '#00ff00' }, nope: { sky0: '#000000' } })
  assert.deepEqual(colors, { midnight: { sky0: '#ff0000' } })
  assert.equal(paletteWith('midnight', colors!.midnight).sky[0], '#ff0000')
  assert.equal(paletteWith('midnight', colors!.midnight).sky[1], PIXEL_PALETTES.midnight.sky[1])
  const doc = applyScene3DTemplate('pixel-neon-city')
  doc.pixelWorld = { ...doc.pixelWorld!, colors, scene: { windows: .9, city: .3 } }
  const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))!
  assert.deepEqual(reopened.pixelWorld?.colors, colors)
  assert.deepEqual(reopened.pixelWorld?.scene, { windows: .9, city: .3 })
  assert.equal(paletteAt(['midnight'], 5, 1, colors).sky[0], '#ff0000')
})

test('city windows switch on and off by cycling, fireflies pulse', () => {
  const at = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.harbor, seconds); return bytes }
  const slots = (bytes: Uint8Array, from: number) => Array.from(bytes.subarray(from * 4, (from + 8) * 4))
  const changed = [0, 3, 7, 12, 20].map(at)
  assert.ok(new Set(changed.map(bytes => slots(bytes, 64).join())).size > 1, 'windows change over time')
  assert.ok(new Set(changed.map(bytes => slots(bytes, 72).join())).size > 1, 'fireflies pulse')
  assert.deepEqual(meteorsAt(40, 1, [700, 214], 5, 'left').filter(m => m.w > 0).every(m => Math.cos(m.z) < 0), true)
})

test('a ringed planet: bands drift by cycling and the ring crosses in front of the disc', () => {
  assert.equal(parsePixelScene({ body: 'planet' })?.body, 'planet')
  const sky = paintSky(200, 120, { seed: 1, horizonRow: 110, stars: 0, moon: { kind: 'planet', x: .5, y: .5, radius: 20, crescent: 0 } })
  const used = new Set(sky.data)
  assert.ok([92, 93, 94, 95].filter(slot => used.has(slot)).length >= 3, 'cloud bands use the cycling slots')
  assert.ok(used.has(96), 'the ring is painted')
  const a = new Uint8Array(1024), b = new Uint8Array(1024)
  writePalette(a, PIXEL_PALETTES.alien, 0); writePalette(b, PIXEL_PALETTES.alien, 2)
  assert.notDeepEqual(Array.from(a.subarray(92 * 4, 96 * 4)), Array.from(b.subarray(92 * 4, 96 * 4)))
  assert.equal(applyScene3DTemplate('pixel-planet-rise').pixelWorld?.scene?.body, 'planet')
})

test('the night train rides the viaduct on the scene clock', () => {
  const root = pixelWorldGroup('pixel-viaduct'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-night-train').pixelWorld!
  const trainX = (seconds: number) => {
    paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720)
    return (root as Group).children.find(child => Math.abs(child.position.z + 23.8) < .01)!.position.x
  }
  const early = trainX(2), later = trainX(4)
  assert.ok(later > early, 'the train moves along the deck')
  assert.equal(trainX(2), early, 'seeking back puts it where it was')
})

test('storm on the lake: every strike thunders and flashes the painted world', () => {
  const doc = applyScene3DTemplate('pixel-storm-lake')
  const bolts = doc.worldSfx!.filter(cue => cue.kind === 'lightning')
  assert.ok(bolts.length >= 4 && bolts.every(cue => cue.sound), 'strikes come with thunder')
  assert.ok(doc.worldSfx!.some(cue => cue.kind === 'rain' && cue.sound))
  const calm = PIXEL_PALETTES.storm, lit = flashPalette(calm, 1.5)
  assert.ok(hexLum(lit.sky[0]) > hexLum(calm.sky[0]) + .15)
  assert.equal(flashPalette(calm, 0), calm)
  const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))!
  assert.equal(reopened.worldSfx?.length, doc.worldSfx?.length)
})

function hexLum(hex: string) {
  const value = parseInt(hex.slice(1), 16)
  return ((value >> 16 & 255) + (value >> 8 & 255) + (value & 255)) / 765
}

test('volcano: lava runs by cycling its slots and the crater smokes', () => {
  const plan = worldPlan('pixel-volcano', resolvePixelScene('pixel-volcano', undefined))
  const cone = plan.layers.find(layer => layer.z === -46)!.paint(680, 157)
  const lava = new Set([...cone.data].filter(slot => slot >= 100 && slot < 108))
  assert.ok(lava.size >= 6, 'rivers step through the lava slots')
  const frame = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.eclipse, seconds); return Array.from(bytes.subarray(400, 432)) }
  assert.notDeepEqual(frame(0), frame(.3), 'the lava pulse moves')
  const doc = applyScene3DTemplate('pixel-volcano')
  assert.deepEqual(doc.worldSfx?.map(cue => cue.kind), ['smoke', 'sparks'])
})

test('drive-in: the big screen plays the recording and its light tints the world', () => {
  const doc = applyScene3DTemplate('pixel-drive-in')
  const screen = doc.slots.find(slot => slot.media === 'screen')!
  assert.equal(screen.screen?.style, 'billboard'); assert.equal(screen.screen?.media, 'video')
  assert.ok(doc.pixelWorld!.screenGlow > 0)
  const plan = worldPlan('pixel-drivein', resolvePixelScene('pixel-drivein', undefined))
  const cars = plan.layers.filter(layer => layer.z > -3)
  assert.equal(cars.length, 2)
  assert.ok(cars.every(layer => layer.paint(...layer.texture).data.includes(108)), 'rear lights use the brake slot')
  const tinted = tintPalette(PIXEL_PALETTES.midnight, '#ff0000', 1)
  assert.ok(parseInt(tinted.water.slice(1, 3), 16) > parseInt(PIXEL_PALETTES.midnight.water.slice(1, 3), 16))
  assert.equal(tintPalette(PIXEL_PALETTES.midnight, '#ff0000', 0), PIXEL_PALETTES.midnight)
})

test('cherry garden: blossom, a lit pagoda, lanterns and drifting petals', () => {
  const plan = worldPlan('pixel-garden', resolvePixelScene('pixel-garden', undefined))
  const shore = plan.layers.find(layer => layer.z === -30)!.paint(736, 96)
  const used = new Set(shore.data)
  assert.ok([110, 111, 112].every(slot => used.has(slot)), 'blossom is lit and shaded')
  assert.ok([...used].some(slot => slot >= 64 && slot < 72), 'pagoda windows glow')
  const pond = plan.layers.find(layer => layer.z === -9)!.paint(360, 50)
  assert.ok([...new Set(pond.data)].some(slot => slot >= 64 && slot < 72), 'stone lanterns glow')
  const doc = applyScene3DTemplate('pixel-cherry-garden')
  assert.equal(doc.worldSfx?.[0].kind, 'snow'); assert.equal(doc.worldSfx?.[0].color, '#ffc2dc')
})

test('coral reef: sunlight shimmers down, schools cross both ways on the clock', () => {
  const plan = worldPlan('pixel-reef', resolvePixelScene('pixel-reef', undefined))
  const water = plan.layers.find(layer => layer.sky)!
  assert.ok([...new Set(water.paint(...water.texture).data)].filter(slot => slot >= 114 && slot < 122).length >= 6, 'rays use the shimmer slots')
  const speeds = plan.layers.filter(layer => layer.drift).map(layer => Math.sign(layer.drift!.speed))
  assert.deepEqual(speeds.sort(), [-1, 1])
  assert.ok(plan.groundY! < 0, 'the seabed lies under the corals')
  const root = pixelWorldGroup('pixel-reef'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-coral-reef').pixelWorld!
  const schools = (seconds: number) => {
    paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720)
    return (root as Group).children.filter(child => child.position.z === -30 || child.position.z === -9).map(child => child.position.x)
  }
  const [a0, b0] = schools(1), [a1, b1] = schools(2)
  assert.ok(a1 > a0 && b1 < b0, 'one school swims right, the other left')
  assert.ok(Math.abs(schools(0)[0]) < 20, 'the schools start in view')
})

test('balloons at dawn: several balloons drift at different depths and bob', () => {
  const plan = worldPlan('pixel-valley', resolvePixelScene('pixel-valley', undefined))
  const balloons = plan.layers.filter(layer => layer.drift?.bob)
  assert.ok(balloons.length >= 4 && new Set(balloons.map(layer => layer.z)).size === balloons.length, 'each at its own depth')
  const cloth = new Set(balloons.flatMap(layer => [...layer.paint(...layer.texture).data]))
  assert.ok([124, 125, 126, 127].filter(slot => cloth.has(slot)).length >= 3, 'balloons wear several colours')
  const root = pixelWorldGroup('pixel-valley'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-balloons').pixelWorld!
  const heights = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.filter(child => child.position.z === -14).map(child => child.position.y) }
  assert.notDeepEqual(heights(0), heights(2), 'balloons bob')
  assert.deepEqual(heights(1), heights(1))
})

test('night fair: the wheel turns, gondolas stay upright and bulbs chase', () => {
  const root = pixelWorldGroup('pixel-fair'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-night-fair').pixelWorld!
  const at = (seconds: number) => {
    paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720)
    const children = (root as Group).children
    return { wheel: children.find(child => child.position.z === -22)!.rotation.z, cabins: children.filter(child => child.position.z === -21.8) }
  }
  const early = at(1), wheel0 = early.wheel, cabin0 = early.cabins[0].position.clone()
  const later = at(5)
  assert.notEqual(later.wheel, wheel0, 'the wheel turns')
  assert.notDeepEqual(later.cabins[0].position.toArray(), cabin0.toArray(), 'gondolas go round')
  assert.ok(later.cabins.every(cabin => cabin.rotation.z === 0), 'gondolas never tilt')
  const bulbs = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.harbor, seconds); return Array.from(bytes.subarray(130 * 4, 138 * 4)).join() }
  assert.notEqual(bulbs(0), bulbs(.2), 'the marquee chases')
})

test('snowy village: smoke rises from the chimneys the painter drew', () => {
  const doc = applyScene3DTemplate('pixel-snow-village')
  const smoke = doc.worldSfx!.filter(cue => cue.kind === 'smoke')
  assert.ok(smoke.length >= 2)
  assert.ok(smoke.every(cue => cue.position.z > -26 && cue.position.y > 0 && Math.abs(cue.position.x) < 35), 'smoke sits on the village plane, above ground')
  assert.ok(doc.worldSfx!.some(cue => cue.kind === 'snow'))
  const plan = worldPlan('pixel-village', resolvePixelScene('pixel-village', undefined))
  const skaters = plan.layers.filter(layer => layer.drift && layer.bottom === 0)
  assert.equal(skaters.length, 3)
  assert.ok(new Set(skaters.map(layer => Math.sign(layer.drift!.speed))).size === 2, 'skaters glide both ways')
})
