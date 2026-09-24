import assert from 'node:assert/strict'
import { test } from 'node:test'
import { parseScene3DDocument } from '../src/features/scene3d/document'
import { cameraEyeAtTime } from '../src/features/scene3d/camera'
import { applyScene3DTemplate, SCENE3D_TEMPLATES } from '../src/features/scene3d/templates'
import { parseMediaScreen } from '../src/features/scene3d/mediaScreen'
import { paletteAt, PIXEL_PALETTES } from '../src/features/scene3d/pixel/pixelPalettes'
import { parsePixelWorld } from '../src/features/scene3d/pixel/pixelWorld'
import { INDEX, paintRange, paintSky, ridge } from '../src/features/scene3d/pixel/pixelPaint'
import { fireworksAt, meteorsAt, snowCover, writePalette } from '../src/features/scene3d/pixel/pixelCycle'
import { createPixelWorldCache, disposePixelWorld, paintPixelWorld, pixelWorldGroup } from '../src/features/scene3d/pixel/pixelWorldSet'
import { dropDressing } from '../src/features/scene3d/dressing'
import type { GpuWorld } from '../src/features/scene3d/gpu'
import { bodyDirection, parsePixelScene, PIXEL_WORLD_KINDS, resolvePixelScene } from '../src/features/scene3d/pixel/pixelScene'
import { eclipseShade, hazeAt, launchGlow, tideLevel, worldPlan } from '../src/features/scene3d/pixel/pixelWorlds'
import { paintJellyfish, paintLoopRange, paintMurmuration, paintPool, paintStarTrails, paintText, paintWheat } from '../src/features/scene3d/pixel/pixelPaintWorlds'
import { layer } from '../src/features/scene3d/pixel/pixelPaint'
import { flashPalette, paletteWith, parsePaletteOverrides, tintPalette } from '../src/features/scene3d/pixel/pixelPalettes'
import { Color, Group, Scene, Vector3, type Mesh } from 'three'
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
    // The whole world's painting, every plane in turn.
    const paint = (layers: typeof plan.layers) => layers.map(layer => Array.from(layer.paint(...layer.texture).data).join('')).join('|')
    const first = paint(plan.layers)
    assert.equal(first, paint(plan.layers), `${kind} is deterministic`)
    assert.notEqual(first, paint(worldPlan(kind, { ...scene, seed: scene.seed + 1 }).layers), `${kind} reimagines with a new seed`)
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

test('waterfall: streaks pour by cycling, with foam and a rainbow in the spray', () => {
  const plan = worldPlan('pixel-falls', resolvePixelScene('pixel-falls', undefined))
  const cliffs = plan.layers.find(layer => layer.z === -34)!
  const used = new Set(cliffs.paint(...cliffs.texture).data)
  assert.ok([140, 141, 142, 143, 144, 145, 146, 147].filter(slot => used.has(slot)).length >= 6, 'streaks step through the fall slots')
  assert.ok(used.has(158), 'steady water between the streaks')
  assert.ok([150, 151, 152, 153, 154].filter(slot => used.has(slot)).length >= 4, 'a rainbow hangs in the spray')
  const at = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.jungle, seconds); return Array.from(bytes.subarray(140 * 4, 148 * 4)).join() }
  assert.notEqual(at(0), at(.2))
})

test('orbit: no ground, a curved planet limb, nebula behind the stars and drifting craft', () => {
  const scene = resolvePixelScene('pixel-orbit', undefined)
  const plan = worldPlan('pixel-orbit', scene)
  assert.equal(plan.ground, 'none')
  const sky = plan.layers.find(layer => layer.sky)!.paint(700, 336)
  assert.ok([160, 161, 162, 163].some(slot => sky.data.includes(slot)), 'nebula gas')
  assert.ok(sky.data.includes(30), 'the moon stays in front of the gas')
  const limb = plan.layers.find(layer => layer.z === -40)!.paint(700, 140)
  const top = (x: number) => { for (let y = 0; y < 140; y++) if (limb.data[y * 700 + x]) return y; return 140 }
  assert.ok(top(10) > top(350) + 10, 'the horizon curves away at the edges')
  assert.ok(plan.layers.some(layer => layer.spin) && plan.layers.some(layer => layer.drift), 'asteroids tumble, craft drift')
  const root = pixelWorldGroup('pixel-orbit'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  paintPixelWorld(root, new Scene(), dir, applyScene3DTemplate('pixel-orbit').pixelWorld!, 1, 720)
  assert.ok(!(root as Group).children.some(child => child.type === 'Mesh' && child.rotation.x === -Math.PI / 2), 'no floor under open space')
})

test('tulip fields: a flower floor in perspective and sails turning on the mills', () => {
  const plan = worldPlan('pixel-tulips', resolvePixelScene('pixel-tulips', undefined))
  assert.equal(plan.ground, 'field')
  const mills = plan.layers.find(layer => layer.z === -28)!
  assert.equal(mills.paint(...mills.texture).hubs?.length, 3)
  const root = pixelWorldGroup('pixel-tulips'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-tulip-fields').pixelWorld!
  const sails = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.filter(child => Math.abs(child.position.z + 27.7) < .01).map(child => child.rotation.z) }
  const early = sails(1), later = sails(4)
  assert.equal(early.length, 3)
  assert.ok(early.every((angle, i) => angle !== later[i]), 'every mill turns')
  assert.ok((root as Group).children.some(child => child.rotation.x === -Math.PI / 2), 'the field lies on the floor')
})

test('neon alley: two walls run along the street and the neon buzzes', () => {
  const plan = worldPlan('pixel-alley', resolvePixelScene('pixel-alley', undefined))
  const walls = plan.layers.filter(layer => layer.turn)
  assert.equal(walls.length, 2)
  assert.ok(walls[0].x! < 0 && walls[1].x! > 0 && walls[0].turn! === -walls[1].turn!, 'facing each other across the street')
  assert.ok([176, 177, 178, 179].some(slot => walls[0].paint(...walls[0].texture).data.includes(slot)), 'neon signs')
  const root = pixelWorldGroup('pixel-alley'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  paintPixelWorld(root, new Scene(), dir, applyScene3DTemplate('pixel-neon-alley').pixelWorld!, 1, 720)
  const turned = (root as Group).children.filter(child => Math.abs(Math.abs(child.rotation.y) - Math.PI / 2) < 1e-6)
  assert.equal(turned.length, 2, 'the wall planes are turned to line the street')
  const tubes = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.neon, seconds); return Array.from(bytes.subarray(176 * 4, 180 * 4)).join() }
  assert.ok(new Set([0, .5, 1.1, 2.3, 3.7, 5.2, 7.9].map(tubes)).size > 1, 'tubes flicker')
})

test('castle fireworks: bursts follow the clock, fade and only burst where asked', () => {
  const plan = worldPlan('pixel-castle', resolvePixelScene('pixel-castle', undefined))
  assert.equal(plan.fireworks, true)
  assert.equal(worldPlan('pixel-lake', resolvePixelScene('pixel-lake', undefined)).fireworks, undefined)
  assert.deepEqual(fireworksAt(4.2, [700, 214]).map(b => b.at.toArray()), fireworksAt(4.2, [700, 214]).map(b => b.at.toArray()))
  assert.ok(fireworksAt(-1, [700, 214]).every(b => b.at.z === 0), 'none without a show')
  let seen = 0
  for (let t = 0; t < 20; t += .5) for (const b of fireworksAt(t, [700, 214])) if (b.at.z > 0) { seen++; assert.ok(b.at.z < 1 && b.at.y > 0 && b.at.y < 214) }
  assert.ok(seen > 15, 'a steady show')
  const castle = plan.layers.find(layer => layer.z === -26)!.paint(448, 136)
  assert.ok([...new Set(castle.data)].some(slot => slot >= 64 && slot < 72), 'lit windows')
  assert.ok([124, 125, 126].some(slot => castle.data.includes(slot)), 'banners fly')
})

test('glowing tide: a beach on the floor whose waves roll in by cycling', () => {
  const plan = worldPlan('pixel-beach', resolvePixelScene('pixel-beach', undefined))
  const shore = plan.layers.find(layer => layer.floor)!
  const sand = shore.paint(...shore.texture)
  assert.ok([180, 181, 182, 183, 184, 185, 186, 187].filter(slot => sand.data.includes(slot)).length >= 6, 'surf bands in the wave slots')
  const waves = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.midnight, seconds); return Array.from(bytes.subarray(180 * 4, 188 * 4)).join() }
  assert.notEqual(waves(0), waves(1))
  const root = pixelWorldGroup('pixel-beach'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  paintPixelWorld(root, new Scene(), dir, applyScene3DTemplate('pixel-glow-tide').pixelWorld!, 1, 720)
  const floor = (root as Group).children.find(child => child.rotation.x === -Math.PI / 2 && child.position.y > 0)
  assert.ok(floor && floor.position.y < .1, 'the beach lies just above the sea')
})

test('lantern festival: flocks rise on the clock and never leave the sky empty', () => {
  const plan = worldPlan('pixel-lanterns', resolvePixelScene('pixel-lanterns', undefined))
  const flocks = plan.layers.filter(layer => layer.drift?.rise)
  assert.equal(flocks.length, 8)
  const root = pixelWorldGroup('pixel-lanterns'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-lantern-festival').pixelWorld!
  const near = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.filter(child => child.position.z === -10 || child.position.z === -9.9).map(child => child.position.y) }
  const [a0] = near(1), [a1] = near(2)
  assert.ok(a1 > a0, 'lanterns rise')
  for (let t = 0; t < 40; t += 1.3) {
    const heights = near(t)
    // The near flock planes are 8 m tall; at their depth the view spans about 0-11 m.
    assert.ok(heights.some(y => y - 4 < 11 && y + 4 > 0), `a near flock is in view at ${t}s`)
  }
  const flames = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.dusk, seconds); return Array.from(bytes.subarray(188 * 4, 192 * 4)).join() }
  assert.notEqual(flames(0), flames(.3), 'flames flicker')
})

test('rainy window: a room frames the city through open panes, rain runs down the glass', () => {
  const plan = worldPlan('pixel-window', resolvePixelScene('pixel-window', undefined))
  const room = plan.layers.find(layer => layer.z === 6)!
  const painted = room.paint(...room.texture)
  const [w, h] = room.texture
  assert.equal(painted.data[Math.round(h * .3) * w + Math.round(w * .4)] === 0 || painted.data[Math.round(h * .3) * w + Math.round(w * .4)] >= 200, true, 'the pane shows the world or rain on the glass')
  assert.ok(painted.data[5 * w + 5] >= 192 && painted.data[5 * w + 5] < 200, 'the wall is painted')
  assert.ok([200, 201, 202, 203, 204, 205, 206, 207].filter(slot => painted.data.includes(slot)).length >= 6, 'rain trails')
  assert.ok(plan.layers.some(layer => layer.z === -36), 'the city lies outside')
  const drops = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.harbor, seconds); return Array.from(bytes.subarray(200 * 4, 208 * 4)).join() }
  assert.notEqual(drops(0), drops(.4))
})

test('night express: layers slide by at parallax speeds and wrap without a seam', () => {
  const plan = worldPlan('pixel-express', resolvePixelScene('pixel-express', undefined))
  const speeds = plan.layers.filter(layer => layer.scroll).sort((a, b) => a.z - b.z).map(layer => layer.scroll!)
  assert.ok(speeds.length === 3 && speeds[0] < speeds[1] && speeds[1] < speeds[2], 'nearer layers slide faster')
  const range = paintLoopRange(720, 100, { body: 40, rim: 41, lightFrom: .5, seed: 3, base: 70, amp: 20, trees: 0 })
  const top = (x: number) => { for (let y = 0; y < 100; y++) if (range.data[y * 720 + x]) return y; return 100 }
  assert.ok(Math.abs(top(0) - top(719)) <= 3, 'the ridge meets itself where it wraps')
  const root = pixelWorldGroup('pixel-express'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const scroll = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, applyScene3DTemplate('pixel-night-express').pixelWorld!, seconds, 720); return (root as Group).children.map(child => (child as Mesh).material?.uniforms?.uScroll?.value ?? 0) }
  assert.notDeepEqual(scroll(1), scroll(2))
  assert.deepEqual(scroll(1), scroll(1))
})

test('a whole day: the sun and moon cross the sky and the light follows the higher one', () => {
  const root = pixelWorldGroup('pixel-daycycle'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-whole-day').pixelWorld!
  const at = (seconds: number) => {
    paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720)
    const [sun, moon] = (root as Group).children.filter(child => child.position.z === -60)
    return { sun: sun.position.clone(), moon: moon.position.clone(), light: dir.position.clone() }
  }
  const dawn = at(1.5), noon = at(6), dusk = at(10.5), night = at(18)
  assert.ok(dawn.sun.x < 0 && dusk.sun.x > 0, 'the sun rises on one side and sets on the other')
  assert.ok(noon.sun.y > dawn.sun.y && noon.sun.y > dusk.sun.y, 'highest at noon')
  assert.ok(night.moon.y > night.sun.y, 'the moon rules the night')
  assert.ok(Math.sign(dawn.light.x) === Math.sign(dawn.sun.x) && Math.sign(night.light.x) === Math.sign(night.moon.x || 1e-9) || night.moon.x === 0, 'light comes from the higher body')
  assert.deepEqual(at(6).sun.toArray(), noon.sun.toArray())
})

test('eclipse: the day darkens as the moon covers the sun, deepest at mid-clip', () => {
  assert.equal(eclipseShade(0), 0)
  assert.equal(eclipseShade(20), 0)
  assert.ok(eclipseShade(10) > .95, 'totality at mid-clip')
  assert.ok(eclipseShade(9) > 0 && eclipseShade(9) < eclipseShade(10) && eclipseShade(11) < eclipseShade(10))
  const root = pixelWorldGroup('pixel-eclipse'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-eclipse').pixelWorld!
  const light = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return dir.intensity }
  assert.ok(light(10) < light(2) * .7, 'the light falls at totality')
  const moon = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.find(child => child.position.z === -59.5)!.position.x }
  assert.ok(Math.abs(moon(10)) < .01 && moon(5) < 0 && moon(15) > 0, 'the moon crosses the sun at mid-clip')
})

test('four seasons: foliage turns with the year and snow piles up level by level', () => {
  assert.equal(snowCover(8), 0, 'no snow in summer')
  assert.ok(snowCover(19) > 0 && snowCover(19) < snowCover(22) && snowCover(22) <= 1, 'snow deepens through winter')
  assert.ok(snowCover(1) > 0 && snowCover(1) < snowCover(0.1), 'and melts in early spring')
  const slots = (seconds: number, from: number, count: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.polar, seconds); return Array.from(bytes.subarray(from * 4, (from + count) * 4)).join() }
  assert.equal(new Set([2, 8, 14, 21].map(t => slots(t, 210, 3))).size, 4, 'four distinct foliages')
  assert.notEqual(slots(19.2, 214, 4), slots(22.8, 214, 4), 'snow levels whiten in turn')
  const plan = worldPlan('pixel-seasons', resolvePixelScene('pixel-seasons', undefined))
  const orchard = plan.layers.find(layer => layer.z === -30)!.paint(640, 70)
  assert.ok([218, 219, 220, 221].every(slot => orchard.data.includes(slot)) && [210, 211, 212].every(slot => orchard.data.includes(slot)))
  assert.deepEqual(applyScene3DTemplate('pixel-four-seasons').worldSfx?.map(cue => [cue.start, cue.end]), [[0, 6], [12, 18], [18, 24]])
})

test('cathedral: stained glass glows in turn and coloured shafts follow it', () => {
  const plan = worldPlan('pixel-cathedral', resolvePixelScene('pixel-cathedral', undefined))
  assert.equal(plan.ground, 'none')
  assert.ok((plan.beams?.length ?? 0) >= 6 && plan.beams!.every(beam => beam.from[1] > beam.to[1]), 'light falls from the windows')
  const wall = plan.layers.find(layer => layer.z === -20)!.paint(360, 264)
  assert.equal([222, 223, 224, 225, 226, 227].filter(slot => wall.data.includes(slot)).length, 6, 'six hues of glass')
  const glass = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.nave, seconds); return Array.from(bytes.subarray(222 * 4, 228 * 4)).join() }
  assert.notEqual(glass(0), glass(3))
  const root = pixelWorldGroup('pixel-cathedral'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const power = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, applyScene3DTemplate('pixel-cathedral').pixelWorld!, seconds, 720); return (root as Group).children.filter(child => child.userData.hue !== undefined).map(child => (child as Mesh).material.uniforms.uPower.value) }
  assert.equal(power(1).length, plan.beams!.length)
  assert.notDeepEqual(power(1), power(5), 'shafts brighten and fade with their glass')
})

test('koi pond: seen from above, koi circle on the ground plane facing where they swim', () => {
  const plan = worldPlan('pixel-koi', resolvePixelScene('pixel-koi', undefined))
  const koi = plan.layers.filter(layer => layer.orbit?.flat)
  assert.ok(koi.length >= 5 && new Set(koi.map(layer => Math.sign(layer.orbit!.speed))).size === 2, 'koi swim both ways round')
  assert.equal(applyScene3DTemplate('pixel-koi-pond').camera.eye[1] > 10, true, 'the camera looks down from above')
  const root = pixelWorldGroup('pixel-koi'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-koi-pond').pixelWorld!
  const fish = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); const mesh = (root as Group).children.find(child => child.position.y === .02)!; return { at: mesh.position.clone(), heading: mesh.rotation.z } }
  const a = fish(2), b = fish(2.1)
  assert.ok(a.at.y === b.at.y && a.at.distanceTo(b.at) > 0, 'koi move across the ground, not up')
  const travel = Math.atan2(-(b.at.z - a.at.z), b.at.x - a.at.x)
  assert.ok(Math.abs(Math.atan2(Math.sin(travel - a.heading), Math.cos(travel - a.heading))) < .2, 'each koi faces where it swims')
})

test('moon caravan: the camels walk frame by frame as the caravan crosses', () => {
  const plan = worldPlan('pixel-caravan', resolvePixelScene('pixel-caravan', undefined))
  const caravan = plan.layers.find(layer => layer.frames)!
  const frames = [0, 1, 2, 3].map(frame => Array.from(caravan.paint(...caravan.texture, frame).data).join(''))
  assert.equal(new Set(frames).size, 4, 'four distinct steps')
  const root = pixelWorldGroup('pixel-caravan'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-moon-caravan').pixelWorld!
  const state = (seconds: number) => {
    paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720)
    const mesh = (root as Group).children.find(child => child.userData.frames) as Mesh
    return { x: mesh.position.x, texture: mesh.material.uniforms.uIndex.value }
  }
  const a = state(1), b = state(1.25)
  assert.ok(b.x > a.x, 'the caravan advances')
  assert.notEqual(a.texture, b.texture, 'and steps to the next frame')
  assert.equal(state(1).texture, a.texture, 'frames follow the clock')
})

test('dropping a painted pixel world releases its palette, and the preview cache reuses a set', () => {
  const root = pixelWorldGroup('pixel-lake')
  const scene = new Scene()
  scene.add(root)
  const dir = { color: new Color(), intensity: 0, position: new Vector3() }
  paintPixelWorld(root, scene, dir, applyScene3DTemplate('pixel-moon-lake').pixelWorld!, 1, 720)
  const palette = root.userData.pixelWorld.palette
  let released = 0
  const dispose = palette.dispose.bind(palette)
  palette.dispose = () => { released++; dispose() }
  dropDressing({ scene, dressing: root } as GpuWorld)
  assert.equal(released, 1)
  assert.equal(root.children.length, 0)
  assert.equal(scene.children.includes(root), false)

  const cache = createPixelWorldCache(2)
  const lake = cache.take('pixel-lake')
  const peaks = cache.take('pixel-peaks')
  assert.equal(cache.take('pixel-lake'), lake)
  assert.equal(cache.size(), 2)
  const orbit = cache.take('pixel-orbit')
  assert.notEqual(orbit, peaks)
  assert.equal(cache.take('pixel-lake'), lake)
  assert.equal(cache.size(), 2)
  cache.release()
  assert.equal(cache.size(), 0)
  disposePixelWorld(pixelWorldGroup('pixel-gallery'))
})

test('synthwave: the grid flows toward the lens and pulses on the beat', () => {
  const plan = worldPlan('pixel-synthwave', resolvePixelScene('pixel-synthwave', undefined))
  assert.equal(plan.clearSky, true)
  const grid = plan.layers.find(layer => layer.scrollY)!
  assert.ok(grid.floor && grid.texture[1] % 20 === 0, 'a floor that tiles along its depth')
  const root = pixelWorldGroup('pixel-synthwave'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-synthwave').pixelWorld!
  const flow = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return ((root as Group).children.find(child => child.rotation.x === -Math.PI / 2) as Mesh).material.uniforms.uScrollY.value }
  assert.ok(flow(2) > flow(1))
  const beat = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.vapor, seconds); return bytes[234 * 4] + bytes[234 * 4 + 1] + bytes[234 * 4 + 2] }
  assert.ok(beat(2) > beat(2.3), 'brightest on the beat')
  assert.equal(beat(2), beat(2.5), 'every half second at 120 BPM')
})

test('monsoon: raindrops ring the lake while it pours', () => {
  const plan = worldPlan('pixel-monsoon', resolvePixelScene('pixel-monsoon', undefined))
  assert.equal(plan.rain, 1)
  const root = pixelWorldGroup('pixel-monsoon'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  paintPixelWorld(root, new Scene(), dir, applyScene3DTemplate('pixel-monsoon').pixelWorld!, 1, 720)
  const lake = (root as Group).children.find(child => (child as Mesh).material?.uniforms?.uRain) as Mesh
  assert.equal(lake.material.uniforms.uRain.value, 1)
  const calm = pixelWorldGroup('pixel-lake')
  paintPixelWorld(calm, new Scene(), dir, applyScene3DTemplate('pixel-moon-lake').pixelWorld!, 1, 720)
  assert.equal(((calm as Group).children.find(child => (child as Mesh).material?.uniforms?.uRain) as Mesh).material.uniforms.uRain.value, 0, 'other lakes stay calm')
  const cues = applyScene3DTemplate('pixel-monsoon').worldSfx!
  assert.ok(cues.some(cue => cue.kind === 'rain' && cue.sound) && cues.some(cue => cue.kind === 'lightning'))
})

test('murmuration: the flock changes shape frame by frame and loops seamlessly', () => {
  const frame = (k: number) => paintMurmuration(420, 150, k, 24, 3, 2600).data
  const bounds = (data: Uint8Array) => { const xs: number[] = []; data.forEach((v, i) => { if (v) xs.push(i % 420) }); return [Math.min(...xs), Math.max(...xs)] }
  assert.notDeepEqual(bounds(frame(0)), bounds(frame(6)), 'the shape changes')
  assert.deepEqual(frame(24), frame(0), 'the last step meets the first')
  const painted = frame(3).filter(Boolean).length
  assert.ok(painted > 1500, 'thousands of birds')
  const plan = worldPlan('pixel-marsh', resolvePixelScene('pixel-marsh', undefined))
  assert.equal(plan.layers.find(layer => layer.frames)?.frames?.count, 24)
})

test('night launch: one liftoff that gathers speed, lit by the engines', () => {
  const root = pixelWorldGroup('pixel-launch'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-night-launch').pixelWorld!
  const at = (seconds: number) => {
    paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720)
    const [rocket, flame] = (root as Group).children.filter(child => child.position.z === -29.8 || child.position.z === -29.7)
    return { y: rocket.position.y, flame: flame.visible }
  }
  const still = at(3), lift = at(7), later = at(9), latest = at(11)
  assert.equal(at(1).y, still.y, 'it waits on the pad')
  assert.equal(still.flame, false)
  assert.ok(lift.flame && lift.y > still.y, 'lift-off with the engines lit')
  assert.ok(latest.y - later.y > later.y - lift.y, 'gathering speed')
  assert.equal(launchGlow(2), 0)
  assert.ok(launchGlow(6) > launchGlow(12) && launchGlow(12) > 0, 'the light fades as it climbs')
  assert.ok(applyScene3DTemplate('pixel-night-launch').worldSfx!.some(cue => cue.kind === 'smoke' && cue.sound))
})

test('crystal cave: a glow sweeps the crystals and the grotto breathes their light', () => {
  const plan = worldPlan('pixel-grotto', resolvePixelScene('pixel-grotto', undefined))
  assert.ok(plan.pulse && plan.rain! > 0, 'a breathing glow and drips on the water')
  const wall = plan.layers.find(layer => layer.z === -26)!.paint(512, 208)
  assert.ok([236, 237, 238, 239, 240, 241, 242, 243].filter(slot => wall.data.includes(slot)).length >= 6, 'crystals span the glow slots')
  const mouth = plan.layers.find(layer => layer.z === 5.6)!.paint(360, 210)
  assert.notEqual(mouth.data[0], 0, 'rock frames the view')
  assert.equal(mouth.data[105 * 360 + 180], 0, 'the mouth opens onto the grotto')
  const crystal = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.grotto, seconds); return Array.from(bytes.subarray(236 * 4, 244 * 4)).join() }
  assert.notEqual(crystal(0), crystal(1.5))
  const root = pixelWorldGroup('pixel-grotto'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-crystal-cave').pixelWorld!
  const light = (seconds: number) => paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720)!.far[0]
  assert.notEqual(light(2), light(6), 'the grotto breathes the crystals\' light')
})

test('starry night: spiral swirls turn by cycling and stars pulse in rings', () => {
  const plan = worldPlan('pixel-starry', resolvePixelScene('pixel-starry', undefined))
  assert.equal(plan.clearSky, true)
  const sky = plan.layers.find(layer => layer.sky)!.paint(700, 214)
  assert.equal([244, 245, 246, 247, 248, 249, 250, 251].filter(slot => sky.data.includes(slot)).length, 8, 'spirals span all swirl slots')
  assert.ok([252, 253, 254].every(slot => sky.data.includes(slot)), 'stars wear rings')
  const swirl = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.starry, seconds); return Array.from(bytes.subarray(244 * 4, 252 * 4)).join() }
  assert.notEqual(swirl(0), swirl(.6), 'the swirls turn')
  assert.ok(plan.layers.some(layer => layer.texture[1] > layer.texture[0] * 3), 'a tall cypress')
})

test('mist rising: banks dissolve in dithered steps, nearest first', () => {
  const plan = worldPlan('pixel-dawnmist', resolvePixelScene('pixel-dawnmist', undefined))
  const banks = plan.layers.filter(layer => layer.dissolve).sort((a, b) => b.z - a.z)
  assert.equal(banks.length, 3)
  assert.ok(banks[0].dissolve!.to < banks[2].dissolve!.to, 'the nearest bank burns off first')
  const root = pixelWorldGroup('pixel-dawnmist'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-mist-rising').pixelWorld!
  const dissolved = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.map(child => (child as Mesh).material?.uniforms?.uDissolve?.value ?? 0).filter(value => value > 0) }
  assert.equal(dissolved(1).length, 0, 'thick mist at first light')
  assert.ok(dissolved(8).some(value => value > 0 && value < 1), 'thinning mid-morning')
  assert.ok(dissolved(19).filter(value => value > 1).length === 3, 'gone by the end')
})

test('roadside motel: the sign spells itself out letter by letter', () => {
  const board = layer(40, 10)
  paintText(board, 'MOTEL', 1, 1, 1, i => 164 + i)
  assert.deepEqual([164, 165, 166, 167, 168].map(slot => board.data.includes(slot)), [true, true, true, true, true], 'each letter in its own slot')
  const lit = (seconds: number) => { const bytes = new Uint8Array(1024); writePalette(bytes, PIXEL_PALETTES.midnight, seconds); return [0, 1, 2, 3, 4].map(k => bytes[(164 + k) * 4]) }
  const early = lit(.6), full = lit(3.5)
  assert.ok(early[0] > early[4], 'the first letter is on before the last')
  assert.ok(full.every(value => value === full[0]), 'then the whole word is lit')
  const plan = worldPlan('pixel-motel', resolvePixelScene('pixel-motel', undefined))
  const motel = plan.layers.find(layer => layer.z === -16)!.paint(340, 90)
  assert.ok([164, 165, 166, 167, 168, 169].every(slot => motel.data.includes(slot)), 'MOTEL and VACANCY on the sign')
})

test('tidal abbey: the tide rises over the causeway and ebbs again', () => {
  const plan = worldPlan('pixel-tidal', resolvePixelScene('pixel-tidal', undefined))
  const tide = plan.tide!
  assert.equal(tideLevel(tide, 0), tide.low)
  assert.ok(Math.abs(tideLevel(tide, 12) - tide.high) < 1e-9, 'high tide at mid-clip')
  const causeway = plan.layers.find(layer => layer.floor)!
  assert.ok(tide.low < causeway.bottom && causeway.bottom < tide.high, 'the causeway is dry at low tide and drowned at high tide')
  const root = pixelWorldGroup('pixel-tidal'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-tidal-abbey').pixelWorld!
  const level = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.find(child => child.position.z === -11)!.position.y }
  assert.ok(level(12) > level(2) && level(22) < level(12))
})

test('mirage: heat haze makes far layers waver and the road flows toward the lens', () => {
  const plan = worldPlan('pixel-mirage', resolvePixelScene('pixel-mirage', undefined))
  assert.ok(plan.layers.filter(layer => layer.shimmer).length >= 2, 'far layers shimmer')
  const road = plan.layers.find(layer => layer.scrollY)!
  assert.ok(road.floor && road.texture[1] % 24 === 0, 'dashes tile along the road')
  const root = pixelWorldGroup('pixel-mirage'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-mirage').pixelWorld!
  const haze = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.map(child => (child as Mesh).material?.uniforms).filter(u => u?.uShimmer?.value > 0).map(u => u.uTime.value) }
  assert.deepEqual(haze(3), [3, 3], 'the haze follows the clock')
})

test('cloud shadows: clouds and their shadows slide across together and wrap', () => {
  const plan = worldPlan('pixel-meadow', resolvePixelScene('pixel-meadow', undefined))
  const clouds = plan.layers.find(layer => layer.z === -40)!, shade = plan.layers.find(layer => layer.floor && layer.scroll)!
  assert.ok(clouds.scroll! < 0 && shade.scroll! < 0, 'both drift the same way')
  const shadow = shade.paint(...shade.texture)
  const covered = shadow.data.filter(Boolean).length / shadow.data.length
  assert.ok(covered > .03 && covered < .4, 'patches of shade, not a blanket')
  const root = pixelWorldGroup('pixel-meadow'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-cloud-shadows').pixelWorld!
  const slide = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.map(child => (child as Mesh).material?.uniforms?.uScroll?.value ?? 0).filter(Boolean) }
  assert.notDeepEqual(slide(1), slide(4))
})

test('fjord: the camera glides between the walls, revealing the depth', () => {
  const doc = applyScene3DTemplate('pixel-fjord')
  assert.equal(doc.camera.family, 'orbit')
  const start = cameraEyeAtTime(doc.camera, 0, doc.duration), end = cameraEyeAtTime(doc.camera, doc.duration, doc.duration)
  assert.ok(Math.hypot(end[0] - start[0], end[2] - start[2]) > 4, 'a real move, not a still')
  const walls = worldPlan('pixel-fjord', resolvePixelScene('pixel-fjord', undefined)).layers.filter(layer => layer.turn)
  assert.equal(walls.length, 2)
  for (const eye of [start, end]) assert.ok(walls.every(wall => Math.abs(eye[0]) < Math.abs(wall.x!)), 'the camera stays between the walls')
})

test('clockwork: meshed gears turn against each other and the pendulum swings', () => {
  const plan = worldPlan('pixel-clockwork', resolvePixelScene('pixel-clockwork', undefined))
  const gears = plan.layers.filter(layer => layer.spin && layer.width > 1.5 && layer.texture[0] === layer.texture[1] && layer.z <= -9.95)
  assert.ok(gears.length >= 8)
  gears.slice(1).forEach((gear, i) => {
    const prev = gears[i]
    assert.ok(Math.sign(gear.spin!) !== Math.sign(prev.spin!), 'neighbours turn opposite ways')
    assert.ok(Math.abs(Math.abs(gear.spin! * gear.width) - Math.abs(prev.spin! * prev.width)) < 1e-9, 'rim speeds match, so teeth mesh')
  })
  const root = pixelWorldGroup('pixel-clockwork'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-clockwork').pixelWorld!
  const angle = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.find(child => child.position.z === -9.6)!.rotation.z }
  assert.ok(angle(.5) > .3 && angle(1.5) < -.3, 'swings one way then the other')
  assert.ok(Math.abs(angle(2)) < 1e-9, 'back through the middle each period')
})

test('orrery: inner planets run faster and a moon circles its moving planet', () => {
  const plan = worldPlan('pixel-orrery', resolvePixelScene('pixel-orrery', undefined))
  const planets = plan.layers.filter(layer => layer.id?.startsWith('planet-'))
  planets.slice(1).forEach((planet, i) => assert.ok(Math.abs(planet.orbit!.speed) < Math.abs(planets[i].orbit!.speed), 'farther is slower'))
  const root = pixelWorldGroup('pixel-orrery'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-orrery').pixelWorld!
  const at = (seconds: number) => {
    paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720)
    const bodies = (root as Group).children.filter(child => child.position.y === .02 || child.position.y === .03)
    const host = bodies[2].position.clone(), moon = bodies.at(-1)!.position.clone()
    return { host, moon }
  }
  for (const t of [0, 3, 9]) {
    const { host, moon } = at(t)
    assert.ok(Math.abs(Math.hypot(moon.x - host.x, moon.z - host.z) - 1.3) < 1e-6, 'the moon keeps its distance from its planet')
  }
  assert.ok(at(3).host.distanceTo(at(0).host) > .1, 'while the planet itself moves on')
})

test('after the storm: the rain stops and a rainbow dithers in', () => {
  const doc = applyScene3DTemplate('pixel-after-storm')
  const rainCue = doc.worldSfx!.find(cue => cue.kind === 'rain')!
  const arc = worldPlan('pixel-rainbow', resolvePixelScene('pixel-rainbow', undefined)).layers.find(layer => layer.dissolve?.appear)!
  assert.ok(rainCue.end <= arc.dissolve!.from, 'the rainbow comes after the rain')
  assert.equal(resolvePixelScene('pixel-rainbow', undefined).body, 'none', 'no sun in front of the rainbow')
  const root = pixelWorldGroup('pixel-rainbow'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const hidden = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, doc.pixelWorld!, seconds, 720); return ((root as Group).children.find(child => child.position.z === -50 && (child as Mesh).material?.uniforms?.uDissolve) as Mesh).material.uniforms.uDissolve.value }
  assert.ok(hidden(4) > 1, 'no rainbow in the storm')
  assert.ok(hidden(11.5) > 0 && hidden(11.5) < 1, 'dithering in')
  assert.ok(hidden(16) <= 0, 'fully there')
})

test('city rising: districts build up from the ground in waves', () => {
  const plan = worldPlan('pixel-risingcity', resolvePixelScene('pixel-risingcity', undefined))
  const districts = plan.layers.filter(layer => layer.grow).sort((a, b) => a.z - b.z)
  assert.equal(districts.length, 3)
  assert.ok(districts[0].grow!.from < districts[2].grow!.from, 'far towers rise first')
  const root = pixelWorldGroup('pixel-risingcity'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-city-rising').pixelWorld!
  const built = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.map(child => (child as Mesh).material?.uniforms?.uGrow?.value).filter(value => value !== undefined && value <= 1) }
  assert.deepEqual(built(.5), [0, 0, 0], 'bare ground at first')
  assert.ok(built(7).some(value => value > 0 && value < 1), 'going up')
  assert.deepEqual(built(18), [1, 1, 1], 'the whole city stands')
})

test('jellyfish: bells pulse frame by frame and each rises in its own lane', () => {
  const width = (frame: number) => { const data = paintJellyfish(40, 72, frame, 8).data; let widest = 0; for (let y = 0; y < 30; y++) { let n = 0; for (let x = 0; x < 40; x++) if (data[y * 40 + x]) n++; widest = Math.max(widest, n) } return widest }
  assert.notEqual(width(2), width(6), 'the bell squeezes and relaxes')
  const root = pixelWorldGroup('pixel-abyss'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  paintPixelWorld(root, new Scene(), dir, applyScene3DTemplate('pixel-jellyfish').pixelWorld!, 3, 720)
  const lanes = (root as Group).children.filter(child => child.userData.frames).map(child => Math.round(child.position.x))
  assert.ok(new Set(lanes).size >= 5, 'they keep their places across the water')
})

test('blizzard: the storm swallows far planes first and clears again', () => {
  const haze = worldPlan('pixel-blizzard', resolvePixelScene('pixel-blizzard', undefined)).haze!
  assert.equal(hazeAt(haze, 1), 0)
  assert.equal(hazeAt(haze, haze.peak), 1)
  assert.equal(hazeAt(haze, haze.to + 1), 0, 'the mountains come back')
  const root = pixelWorldGroup('pixel-blizzard'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-blizzard').pixelWorld!
  const thickness = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.map(child => ({ z: child.position.z, haze: (child as Mesh).material?.uniforms?.uHaze?.value as number | undefined })).filter(item => item.haze !== undefined).sort((a, b) => a.z - b.z) }
  const peak = thickness(haze.peak)
  assert.ok(peak[0].haze! > peak[peak.length - 1].haze!, 'the far range fades before the near reeds')
  assert.ok(thickness(1).every(item => item.haze === 0), 'a clear morning first')
})

test('lantern walk: the lamp travels with its bearer and lights the other planes, not the bearer', () => {
  const root = pixelWorldGroup('pixel-lantern'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-lantern-walk').pixelWorld!
  const lamps = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.map(child => (child as Mesh).material?.uniforms?.uCarry?.value as { x: number; w: number } | undefined).filter(value => value !== undefined) }
  const early = lamps(2).filter(lamp => lamp.w > 0).map(lamp => lamp.x), later = lamps(12).filter(lamp => lamp.w > 0).map(lamp => lamp.x)
  assert.ok(early.length > 3, 'the wood, bank and reeds catch the light')
  assert.ok(later[0] - early[0] > 4, 'the light walks along the shore')
  const bearer = (root as Group).getObjectsByProperty('type', 'Mesh').find(mesh => mesh.userData.frames) as Mesh
  assert.equal((bearer.material as { uniforms: { uCarry: { value: { w: number } } } }).uniforms.uCarry.value.w, 0, 'the bearer stays a silhouette')
})

test('empire of light: the sky keeps its daylight palette while the street below is night', () => {
  const root = pixelWorldGroup('pixel-empire'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  paintPixelWorld(root, new Scene(), dir, applyScene3DTemplate('pixel-empire-of-light').pixelWorld!, 5, 720)
  const planes = (root as Group).children.filter(child => (child as Mesh).material?.uniforms?.uPalette).sort((a, b) => a.position.z - b.position.z)
  const palette = (plane: typeof planes[number]) => (plane as Mesh).material.uniforms.uPalette.value as { image: { data: Uint8Array } }
  const sky = palette(planes[0]), street = palette(planes[planes.length - 1])
  assert.notEqual(sky, street, 'two palettes at once')
  const brightness = (texture: typeof sky, slot: number) => texture.image.data[slot * 4] + texture.image.data[slot * 4 + 1] + texture.image.data[slot * 4 + 2]
  assert.ok(brightness(sky, INDEX.sky + 4) > brightness(street, INDEX.sky + 4) * 2, 'daylight blue over a night street')
})

test('star trails: every star sweeps the same arc round the pole and is traced in over the shot', () => {
  const trails = paintStarTrails(200, 120, 7, .5, .5, 60)
  const drawn = [...trails.data.keys()].filter(at => trails.data[at])
  assert.ok(drawn.length > 600, 'long arcs, not dots')
  assert.ok(drawn.every(at => trails.order![at] >= 1), 'every texel knows when it appears')
  const first = drawn.filter(at => trails.order![at] < 20).length, last = drawn.filter(at => trails.order![at] > 235).length
  assert.ok(first > 0 && last > 0, 'traced from start to end')
  const root = pixelWorldGroup('pixel-startrails'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-star-trails').pixelWorld!
  const exposure = (seconds: number) => { paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720); return (root as Group).children.map(child => (child as Mesh).material?.uniforms?.uReveal?.value as number).filter(value => value <= 1) }
  assert.deepEqual(exposure(0), [0])
  assert.ok(exposure(10)[0] > .3 && exposure(10)[0] < .7, 'half traced')
  assert.deepEqual(exposure(23), [1])
})

test('wheat in the wind: nearer stalks lean further, all on the one scene clock', () => {
  const wheat = paintWheat(200, 40, 3, .02)
  assert.ok(wheat.data.every(index => index === 0 || (index >= INDEX.wheat && index < INDEX.wheat + 4) || index === INDEX.tulip), 'gold and poppies only')
  assert.ok(wheat.data.some(index => index === INDEX.tulip), 'the odd poppy')
  const plan = worldPlan('pixel-wheat', resolvePixelScene('pixel-wheat', undefined))
  const swaying = plan.layers.filter(layer => layer.sway).sort((a, b) => a.z - b.z)
  assert.ok(swaying.length >= 4 && swaying[swaying.length - 1].sway! > swaying[0].sway!, 'the front bends the most')
  const root = pixelWorldGroup('pixel-wheat'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  paintPixelWorld(root, new Scene(), dir, applyScene3DTemplate('pixel-wheat-wind').pixelWorld!, 7.5, 720)
  const clocks = (root as Group).children.map(child => (child as Mesh).material?.uniforms).filter(uniforms => uniforms?.uSway?.value > 0).map(uniforms => uniforms.uTime.value)
  assert.deepEqual(new Set(clocks), new Set([7.5]), 'gusts follow the scene clock, so export matches the preview')
})

test('pool in the sun: caustics play only over the water, on the scene clock', () => {
  const pool = paintPool(100, 70)
  const water = pool.data.filter(index => index >= INDEX.pool && index < INDEX.pool + INDEX.poolSteps).length
  assert.ok(water > 1000 && pool.data.includes(INDEX.coping), 'blue water inside a stone rim')
  const plan = worldPlan('pixel-pool', resolvePixelScene('pixel-pool', undefined))
  assert.deepEqual(plan.layers.filter(layer => layer.caustics).map(layer => layer.floor), [true], 'one lit pool floor')
  const root = pixelWorldGroup('pixel-pool'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  paintPixelWorld(root, new Scene(), dir, applyScene3DTemplate('pixel-hockney-pool').pixelWorld!, 4.25, 720)
  const floor = (root as Group).children.map(child => (child as Mesh).material?.uniforms).find(uniforms => uniforms?.uCaustic?.value > 0)!
  assert.equal(floor.uTime.value, 4.25)
})

test('metaphysical square: the floor samples the arcade for its shadow and follows the moving sun', () => {
  const root = pixelWorldGroup('pixel-piazza'), dir = { color: new Color(), intensity: 0, position: new Vector3() }
  const pixel = applyScene3DTemplate('pixel-metaphysical-square').pixelWorld!
  const sun = (seconds: number) => {
    paintPixelWorld(root, new Scene(), dir, pixel, seconds, 720)
    const meshes = (root as Group).children as Mesh[]
    const floor = meshes.find(mesh => mesh.material?.uniforms?.uShadow?.value === 1)!
    const caster = meshes.find(mesh => mesh.material?.uniforms?.uIndex?.value === floor.material.uniforms.uCaster.value)
    assert.ok(caster && caster !== floor, 'the shadow comes from the arcade plane')
    return (floor.material.uniforms.uSunDir.value as Vector3).clone()
  }
  const morning = sun(1), evening = sun(22)
  assert.ok(morning.z < 0 && morning.y > 0, 'the sun stands low behind the square')
  assert.ok(morning.x < 0 && evening.x > 0, 'it crosses from left to right, so the shadows swing')
})
