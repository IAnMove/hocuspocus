import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { FX_CATALOG, parseSceneFx, switchFxKind, type SceneFx } from '../src/features/sceneFx/types.ts'
import { needsFrameSource, paintSceneFx } from '../src/features/sceneFx/paint.ts'
import {
  CANDLE_DARK_REACH, CINEMATIC_KINDS, RAY_SPREAD, blendsWithFrame, candlelightAt, candlelightField, canvasTexture,
  cinematicPainter, filmGrainTile, grainCell, lightRays, loopNoise, vignetteShade,
} from '../src/features/sceneFx/cinematicPaint.ts'
import { GLITCH_STEP_RATE, glitchBursts, glitchFrame, tearPixels } from '../src/features/sceneFx/glitchPaint.ts'
import { withFxShowcase } from '../src/features/sceneFx/showcase.ts'
import { parseScreenBackdrop } from '../src/features/scene3d/screenBackdrop.ts'
import { createDefaultScene3DDocument, parseScene3DDocument } from '../src/features/scene3d/document.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const locale = (code: string) => JSON.parse(readFileSync(join(HERE, `../src/i18n/locales/${code}/sceneFx.json`), 'utf8'))

type Fill = { kind: string; args: unknown[]; stops: Array<[number, string]> } | unknown
type Call = { name: string; args: unknown[]; fill: Fill; alpha: unknown; composite: unknown }

/** A 2D context that records every draw call with its style; gradients keep their stops. With
 * `pixels`, getImageData and putImageData read and write that full-frame RGBA buffer. */
function recorder(width: number, height: number, pixels?: Uint8ClampedArray) {
  const calls: Call[] = []
  const state: Record<string, unknown> = { canvas: { width, height }, fillStyle: '#000', strokeStyle: '#000', globalAlpha: 1,
    globalCompositeOperation: 'source-over', imageSmoothingEnabled: true, lineWidth: 1, lineCap: 'butt', font: '', textAlign: 'left' }
  const gradient = (kind: string, args: unknown[]) => {
    const stops: Array<[number, string]> = []
    return { kind, args, stops, addColorStop(offset: number, color: string) { stops.push([offset, color]) } }
  }
  const snapshot = (fill: unknown) => fill && typeof fill === 'object' && 'stops' in fill
    ? { kind: (fill as { kind: string }).kind, args: (fill as { args: unknown[] }).args, stops: [...(fill as { stops: Array<[number, string]> }).stops] } : fill
  const context = new Proxy(state, {
    get(target, prop, receiver) {
      if (prop === 'createRadialGradient' || prop === 'createLinearGradient') return (...args: unknown[]) => gradient(prop, args)
      if (pixels && prop === 'getImageData') return (_x: number, _y: number, w: number, h: number) => ({ data: new Uint8ClampedArray(pixels), width: w, height: h })
      if (pixels && prop === 'putImageData') return (image: { data: Uint8ClampedArray }) => { pixels.set(image.data) }
      if (typeof prop === 'string' && !(prop in target)) {
        return (...args: unknown[]) => {
          calls.push({ name: prop, args, fill: snapshot(target.fillStyle), alpha: target.globalAlpha, composite: target.globalCompositeOperation })
          return prop === 'measureText' ? { width: 10 } : undefined
        }
      }
      return Reflect.get(target, prop, receiver)
    },
  })
  return { context: context as unknown as CanvasRenderingContext2D, calls }
}

const fx = (kind: string, patch: Partial<SceneFx> = {}) => parseSceneFx([{ id: kind, kind, start: 0, end: 6, seed: 5, ...patch }])[0]
const draw = (cue: SceneFx, time: number, width = 640, height = 360, pixels?: Uint8ClampedArray) => {
  const { context, calls } = recorder(width, height, pixels)
  cinematicPainter(cue.kind)!(context, cue, time, width, height)
  return calls
}
const gradients = (calls: Call[]) => calls.map(call => call.fill).filter((fill): fill is { kind: string; args: number[]; stops: Array<[number, string]> } =>
  Boolean(fill && typeof fill === 'object' && 'stops' in fill))
const alphaOf = (color: string) => Number(color.match(/, ([\d.]+)\)$/)?.[1])
/** A ramp from black to white across the frame, with a little colour, as RGBA. */
function ramp(width: number, height: number) {
  const pixels = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y++) for (let x = 0; x < width; x++) {
    const i = (y * width + x) * 4, value = Math.round(x * 255 / (width - 1))
    pixels[i] = value; pixels[i + 1] = Math.round(value * .8 + y % 7); pixels[i + 2] = Math.round(255 - value * .6); pixels[i + 3] = 255
  }
  return pixels
}
const mean = (values: ArrayLike<number>, step = 1, from = 0) => {
  let sum = 0, count = 0
  for (let i = from; i < values.length; i += step) { sum += values[i]; count++ }
  return sum / count
}

test('the six cinematic effects are a catalog collection with their own defaults and names', () => {
  const pack = FX_CATALOG.filter(item => item.collection === 'cinematic')
  assert.deepEqual(pack.map(item => item.id), [...CINEMATIC_KINDS])
  assert.deepEqual(pack.map(item => [item.id, item.color, item.size]), [
    ['candlelight', '#ffb35c', 45], ['vignette', '#000000', 60], ['film_grain', '#d8d0c0', 100],
    ['light_rays', '#ffd27a', 120], ['glitch', '#39ff6a', 6], ['canvas', '#efdcb8', 100],
  ])
  const rays = fx('light_rays')
  assert.deepEqual([rays.x, rays.y, rays.rotation, rays.size], [28, 0, 62, 120], 'light comes from high on the left by default')
  assert.deepEqual([fx('candlelight').x, fx('candlelight').y, fx('candlelight').rotation], [50, 50, 0], 'the others keep the shared placement')
  const given = fx('light_rays', { x: 90, y: 10, rotation: 150, size: 80 })
  assert.deepEqual([given.x, given.y, given.rotation, given.size], [90, 10, 150, 80])
  for (const code of ['en', 'es']) {
    const names = locale(code)
    for (const id of CINEMATIC_KINDS) assert.ok(names.presets[id], `${code} ${id}`)
    assert.ok(names.collections.cinematic, code)
  }
  assert.equal(locale('es').presets.candlelight, 'Luz de vela')
  const showcase = withFxShowcase({ version: 1 as const, name: 'FX', layers: [], width: 640, height: 360, duration: 3 })
  const shown = showcase.sfx.find(item => item.kind === 'light_rays')!
  assert.deepEqual([shown.size, shown.x, shown.y, shown.rotation], [120, 28, 0, 62])
  assert.equal(showcase.sfx.find(item => item.kind === 'vignette')?.size, 60)
})

test('switching to or from an effect with its own placement resets it', () => {
  assert.deepEqual(switchFxKind({ kind: 'sparks' }, 'light_rays'), { kind: 'light_rays', color: '#ffd27a', size: 120, x: 28, y: 0, rotation: 62 })
  assert.deepEqual(switchFxKind({ kind: 'light_rays' }, 'candlelight'), { kind: 'candlelight', color: '#ffb35c', size: 45, x: 50, y: 50, rotation: 0 })
  assert.deepEqual(switchFxKind({ kind: 'vignette' }, 'sparks'), { kind: 'sparks', color: '#ffbb55', size: 65 })
})

test('the effects that blend with the picture ask the editor for the frame under them', () => {
  for (const kind of ['candlelight', 'film_grain', 'light_rays', 'glitch', 'canvas']) {
    assert.equal(blendsWithFrame(kind), true, kind)
    assert.equal(needsFrameSource(kind), true, kind)
  }
  assert.equal(needsFrameSource('vignette'), false, 'a vignette only darkens: it paints the same over anything')
  assert.equal(needsFrameSource('sparks'), false)
  assert.equal(cinematicPainter('sparks'), undefined)
})

test('the moving effects are pure functions of seed and time and loop over the cue', () => {
  for (const kind of ['candlelight', 'light_rays', 'glitch']) {
    for (const [start, end] of [[0, 6], [1.3, 5.67], [0, 2], [12.5, 32.5]]) {
      const cue = fx(kind, { start, end, seed: 11, intensity: 1.5 })
      const span = end - start
      // A glitch is drawn only in a burst: check it at the start of one.
      const at = kind === 'glitch' ? glitchBursts(cue)[0].start + .01 : span / 3
      assert.deepEqual(draw(cue, at), draw(cue, at), `${kind} ${start}-${end}: same seed and time, same frame`)
      assert.deepEqual(draw(cue, span), draw(cue, 0), `${kind} ${start}-${end}: the frame at end is the frame at start`)
      if (kind !== 'glitch') assert.notDeepEqual(draw(cue, at), draw(cue, 0), `${kind}: it moves in between`)
      assert.notDeepEqual(draw(cue, at), draw({ ...cue, seed: 12 }, at), `${kind}: another seed, another frame`)
    }
  }
  const grain = fx('film_grain', { start: 1.3, end: 5.67 })
  assert.deepEqual(filmGrainTile(grain, 4.37, 64, 36), filmGrainTile(grain, 0, 64, 36))
  for (const cycles of [1, 3, 17]) assert.ok(Math.abs(loopNoise(9, .999999, cycles) - loopNoise(9, 0, cycles)) < 1e-4, `noise with ${cycles} knots is periodic`)
  // Through the shared painter: a later cue repeats over its own span and is over at its end.
  const late = fx('candlelight', { start: 2, end: 8 })
  const at = (seconds: number) => { const { context, calls } = recorder(320, 180); paintSceneFx(context, 320, 180, seconds, [late]); return calls }
  assert.deepEqual(at(2), at(2))
  assert.equal(at(8).length, 0)
})

test('candlelight lights what is near the flame, darkens what is far, and flickers without strobing', () => {
  const cue = fx('candlelight', { x: 30, y: 40 })
  const width = 1280, height = 720, grey = [120, 120, 120] as const
  const field = candlelightField(cue, 1, width, height)
  assert.ok(Math.abs(field.x - width * .3) < field.radius * .05 && Math.abs(field.y - height * .4) < field.radius * .05, 'centred on x, y, swaying a little')
  assert.ok(Math.abs(field.radius - height * .45) < height * .45 * .02, 'size is the radius in % of the frame height')
  const luma = (pixel: readonly number[]) => pixel[0] + pixel[1] + pixel[2]
  const near = candlelightAt(field, field.x, field.y, grey), edge = candlelightAt(field, field.x + field.radius * .7, field.y, grey)
  const far = candlelightAt(field, width, height, grey)
  assert.ok(luma(near) > luma(edge) && luma(edge) > luma(grey) && luma(grey) > luma(far), `${near} > ${edge} > ${grey} > ${far}`)
  assert.ok(near[0] > near[1] && near[1] > near[2], 'warm light')
  assert.ok(Math.hypot(width - field.x, height - field.y) > field.radius * CANDLE_DARK_REACH && luma(far) > luma(grey) * .5, 'the darkening far away is slight')
  assert.deepEqual(candlelightAt(field, field.x, field.y, [0, 0, 0]).map(value => value > 0), [true, true, true], 'the flame glows in the air even over black')
  // Intensity drives the light and the darkness together.
  const at = (intensity: number) => candlelightField(fx('candlelight', { intensity }), 1, width, height)
  for (const [low, high] of [[.3, 1], [1, 1.6]]) {
    const [a, b] = [at(low), at(high)]
    assert.ok(b.light > a.light && b.glow > a.glow && b.darkness > a.darkness, `${low} < ${high}`)
    assert.ok(luma(candlelightAt(b, b.x, b.y, grey)) > luma(candlelightAt(a, a.x, a.y, grey)))
    assert.ok(luma(candlelightAt(b, 0, height, grey)) < luma(candlelightAt(a, 0, height, grey)))
  }
  // A few hertz of organic flicker: visible over a second, smooth from one 60 fps frame to the next.
  const gains = Array.from({ length: 6 * 240 }, (_, i) => candlelightField(cue, i / 240, width, height).flicker)
  assert.ok(Math.max(...gains) - Math.min(...gains) > .12, 'it flickers')
  assert.ok(Math.max(...gains) <= 1.16 && Math.min(...gains) >= .84)
  const steps = gains.slice(4).map((gain, i) => Math.abs(gain - gains[i]))
  assert.ok(Math.max(...steps) < .04, `no strobe: largest change in 1/60 s ${Math.max(...steps)}`)
  // The painter draws those layers: darkness over the frame, colour dodge and glow screened, centred on the flame.
  const calls = draw(cue, 1, width, height)
  assert.deepEqual(calls.filter(call => call.name === 'fillRect').map(call => call.composite), ['source-over', 'color-dodge', 'screen'])
  for (const gradient of gradients(calls)) assert.deepEqual(gradient.args.slice(0, 2), [field.x, field.y])
  const [shade, light] = gradients(calls)
  assert.equal(alphaOf(shade.stops[0][1]), 0, 'no darkness on the flame')
  assert.ok(Math.abs(alphaOf(shade.stops.at(-1)![1]) - field.darkness) < 1e-3)
  assert.equal(light.stops.at(-1)![1], 'rgba(0, 0, 0, 1)', 'the dodge fades to nothing at the radius')
})

test('a vignette is darker at the corners than in the centre; size is its reach, intensity its strength', () => {
  const cue = fx('vignette')
  assert.equal(vignetteShade(cue, 0), 0)
  assert.ok(vignetteShade(cue, .3) < .02, 'the middle stays clear')
  assert.ok(vignetteShade(cue, 1) < vignetteShade(cue, Math.SQRT2) && vignetteShade(cue, Math.SQRT2) > .6, 'darkest at the corners')
  assert.ok(vignetteShade(fx('vignette', { intensity: 1.5 }), 1.2) > vignetteShade(cue, 1.2) && vignetteShade(cue, 1.2) > vignetteShade(fx('vignette', { intensity: .4 }), 1.2))
  assert.ok(vignetteShade(fx('vignette', { size: 100 }), .6) > vignetteShade(cue, .6) && vignetteShade(cue, .8) > vignetteShade(fx('vignette', { size: 30 }), .8), 'a larger size reaches further in')
  assert.deepEqual(draw(cue, 0), draw(cue, 3.3), 'static')
  const calls = draw(fx('vignette', { x: 40, y: 60 }), 0, 1000, 500)
  assert.deepEqual(calls.filter(call => call.name === 'translate')[0].args, [400, 300], 'centred on x, y')
  assert.deepEqual(calls.filter(call => call.name === 'scale')[0].args, [500, 250], 'an ellipse that fits the frame')
  const black = gradients(calls)[0].stops.map(([, color]) => color)
  assert.ok(black.every(color => color.startsWith('rgba(0, 0, 0, ')), 'black by default')
  assert.ok(alphaOf(black[0]) < alphaOf(black.at(-1)!))
})

test('film grain is monochrome, new on every frame, and leaves the mean of the picture as it was', () => {
  const cue = fx('film_grain'), columns = 160, rows = 90
  const tile = filmGrainTile(cue, 1, columns, rows)
  assert.deepEqual(tile, filmGrainTile(cue, 1, columns, rows), 'deterministic')
  for (const fps of [24, 25, 30, 50, 60]) {
    const frames = Array.from({ length: fps }, (_, k) => filmGrainTile(cue, k / fps, 8, 4).join())
    assert.equal(new Set(frames).size, fps, `new grain on every frame at ${fps} fps`)
  }
  for (let i = 0; i < tile.length; i += 4) assert.ok(tile[i] === tile[i + 1] && tile[i] === tile[i + 2] && tile[i + 3] === 255)
  assert.ok(Math.abs(mean(tile, 4) - 127.5) < .5, `grain centred on mid grey: ${mean(tile, 4)}`)
  // Overlay is linear in the grain: the picture keeps its mean, and the grain is subtle.
  const overlay = (base: number, grain: number) => base <= .5 ? 2 * base * grain : 1 - 2 * (1 - base) * (1 - grain)
  const picture = ramp(columns, rows), grained = picture.map((value, i) => i % 4 === 3 ? value : 255 * overlay(value / 255, tile[i - i % 4] / 255))
  for (const channel of [0, 1, 2]) assert.ok(Math.abs(mean(grained, 4, channel) - mean(picture, 4, channel)) < .6, `channel ${channel}`)
  const deviation = (data: Uint8ClampedArray) => Math.sqrt(mean(Array.from(data.filter((_, i) => i % 4 === 0), value => (value - 127.5) ** 2)))
  assert.ok(deviation(tile) > 5 && deviation(tile) < 16, `subtle: ${deviation(tile)} levels`)
  assert.ok(deviation(filmGrainTile(fx('film_grain', { intensity: 2 }), 1, columns, rows)) > deviation(tile) * 1.5)
  assert.ok(deviation(filmGrainTile(fx('film_grain', { intensity: .3 }), 1, columns, rows)) < deviation(tile) * .5)
  assert.ok(grainCell(1080, 100) === 2 && grainCell(1080, 200) === 4 && grainCell(540, 50) === 1, 'size scales the grain')
})

test('light rays fan out from x, y along rotation, as long as size, and drift slowly', () => {
  const cue = fx('light_rays', { x: 20, y: 0, rotation: 70, size: 100 })
  const rays = lightRays(cue, 1, 1280, 720)
  assert.deepEqual([rays.x, rays.y, rays.length], [256, 0, 720])
  for (const shaft of rays.shafts) {
    assert.ok(Math.abs(shaft.angle - 70 * Math.PI / 180) <= RAY_SPREAD / 2 + .04, 'inside the fan')
    assert.ok(shaft.reach <= rays.length && shaft.reach >= rays.length * .5)
  }
  const total = (intensity: number) => {
    const value = lightRays(fx('light_rays', { intensity }), 1, 1280, 720)
    return { count: value.shafts.length, light: value.shafts.reduce((sum, shaft) => sum + shaft.alpha, 0) }
  }
  assert.ok(total(1.6).count > total(1).count && total(1).count > total(.4).count, 'more shafts')
  assert.ok(total(1.6).light > total(1).light && total(1).light > total(.4).light, 'brighter')
  const next = lightRays(cue, 1 + 1 / 24, 1280, 720)
  assert.ok(rays.shafts.every((shaft, i) => Math.abs(shaft.angle - next.shafts[i].angle) < .004 && Math.abs(shaft.alpha - next.shafts[i].alpha) < .01), 'a slow shimmer')
  const calls = draw(cue, 1)
  assert.equal(calls.find(call => call.name === 'translate')?.args.join(), `${640 * .2},0`)
  assert.ok(calls.filter(call => call.name === 'fill').every(call => call.composite === 'screen'))
  assert.ok(calls.filter(call => call.name === 'rotate').some(call => Math.abs(Number(call.args[0]) - 70 * Math.PI / 180) < 1e-9), 'the haze points along rotation')
})

test('glitch corrupts the frame in bursts, differently on every step, and leaves it alone between them', () => {
  const cue = fx('glitch')
  const bursts = glitchBursts(cue)
  assert.equal(bursts.length, 3)
  for (const [index, burst] of bursts.entries()) {
    assert.ok(burst.start >= index * 2 && burst.end <= (index + 1) * 2 && burst.end - burst.start >= .16, JSON.stringify(burst))
  }
  const quiet = (bursts[0].end + bursts[1].start) / 2
  assert.equal(glitchFrame(cue, quiet, 640, 360), null)
  assert.equal(draw(cue, quiet).length, 0, 'nothing drawn between bursts')
  const frames = Array.from({ length: 4 }, (_, k) => bursts[0].start + (k + .5) / GLITCH_STEP_RATE).filter(time => time < bursts[0].end)
    .map(time => glitchFrame(cue, time, 640, 360))
  assert.ok(frames.length >= 3 && frames.every(Boolean))
  for (let i = 1; i < frames.length; i++) assert.notDeepEqual(frames[i], frames[i - 1], 'the corruption changes on every step')
  for (const frame of frames) {
    assert.ok(frame!.tears.length >= 1)
    for (const tear of frame!.tears) assert.ok(tear.y >= 0 && tear.y + tear.height <= 360 && tear.height >= 1)
  }
  // Intensity: more bursts, longer shifts.
  assert.ok(glitchBursts(fx('glitch', { intensity: 2 })).length > bursts.length && glitchBursts(fx('glitch', { intensity: .3 })).length < bursts.length)
  const shifts = (intensity: number) => {
    const strong = fx('glitch', { intensity, seed: 3 })
    const values = glitchBursts(strong).flatMap(burst => [0, 1, 2].map(k => glitchFrame(strong, burst.start + (k + .5) / GLITCH_STEP_RATE, 640, 360)))
      .flatMap(frame => frame?.tears.filter(tear => tear.shift).map(tear => Math.abs(tear.shift)) ?? [])
    return mean(values)
  }
  assert.ok(shifts(2) > shifts(.5) * 2, `${shifts(2)} vs ${shifts(.5)}`)
  // The tears move real pixels, with red and blue split apart.
  const band = new Uint8ClampedArray(8 * 4)
  for (let x = 0; x < 8; x++) band.set([x * 10, x * 10 + 1, x * 10 + 2, 255], x * 4)
  tearPixels(band, 8, 1, 2, 1)
  assert.deepEqual([band[4 * 4], band[4 * 4 + 1], band[4 * 4 + 2]], [10, 21, 32], 'red from 3 px left, green from 2, blue from 1')
  assert.deepEqual([band[0], band[1], band[2]], [50, 61, 72], 'what leaves one side comes back on the other')
  const width = 64, height = 36, source = ramp(width, height)
  const painted = new Uint8ClampedArray(source)
  draw(fx('glitch', { intensity: 2 }), glitchBursts(fx('glitch', { intensity: 2 }))[0].start + .01, width, height, painted)
  assert.notDeepEqual(painted, source, 'a burst changes the pixels of the frame')
  const calm = new Uint8ClampedArray(source)
  draw(cue, quiet, width, height, calm)
  assert.deepEqual(calm, source)
})

test('the canvas texture is static, only darkens, is warm, and deepens with intensity', () => {
  const cue = fx('canvas'), columns = 96, rows = 54
  const texture = canvasTexture(cue, columns, rows, 1080)
  assert.deepEqual(texture, canvasTexture(cue, columns, rows, 1080))
  assert.notDeepEqual(texture, canvasTexture({ ...cue, seed: 6 }, columns, rows, 1080))
  assert.notDeepEqual(texture, canvasTexture({ ...cue, size: 160 }, columns, rows, 1080), 'size scales the weave')
  const [r, g, b] = [0, 1, 2].map(channel => mean(texture, 4, channel))
  assert.ok(r > g && g > b && b > 150, `warm and light: ${r} ${g} ${b}`)
  assert.ok(mean(texture, 4, 3) === 255)
  const light = Math.min(...[0, 1, 2].map(channel => mean(texture, 4, channel))) / 255
  assert.ok(light > .6, 'subtle')
  const values = new Set(texture.filter((_, i) => i % 4 === 0))
  assert.ok(values.size > 20, 'a texture, not a flat tint')
  const deep = canvasTexture({ ...cue, intensity: 1.8 }, columns, rows, 1080), faint = canvasTexture({ ...cue, intensity: .4 }, columns, rows, 1080)
  assert.ok(mean(deep, 4, 2) < mean(texture, 4, 2) && mean(texture, 4, 2) < mean(faint, 4, 2))
  // Without an off-screen canvas (Node) the painter draws nothing rather than failing.
  assert.equal(draw(cue, 0).length, 0)
})

test('the cinematic effects work as Video 3D screen effects and in a screen backdrop', () => {
  const cues = CINEMATIC_KINDS.map(kind => ({ id: kind, kind, start: 0, end: 6 }))
  const backdrop = parseScreenBackdrop({ color: '#000000', sfx: [cues[0], cues[3]] })!
  assert.deepEqual(backdrop.sfx.map(cue => [cue.kind, cue.size]), [['candlelight', 45], ['light_rays', 120]])
  const doc = { ...createDefaultScene3DDocument(), duration: 6, sfx: parseSceneFx(cues), screenBackdrop: backdrop }
  const reopened = parseScene3DDocument(JSON.parse(JSON.stringify(doc)))
  assert.deepEqual(reopened?.sfx, doc.sfx)
  assert.deepEqual(reopened?.screenBackdrop, backdrop)
})
