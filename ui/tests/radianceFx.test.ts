import assert from 'node:assert/strict'
import test from 'node:test'
import { drawnOnFrame, paintSceneFx } from '../src/features/sceneFx/paint.ts'
import { parseSceneFx, type SceneFx } from '../src/features/sceneFx/types.ts'
import { SHOCK_REACH, shieldBody, shieldState, shockwaveState, richer, whiter } from '../src/features/sceneFx/radiancePaint.ts'

type Arc = { x: number; y: number }

/** A 2D context that keeps every colour it is given (styles and gradient stops) and the centre of every arc. */
function recorder(width = 640, height = 360) {
  const colors: string[] = [], arcs: Arc[] = []
  let radial = 0
  const state: Record<string, unknown> = { canvas: { width, height }, fillStyle: '#000', strokeStyle: '#000', globalAlpha: 1,
    globalCompositeOperation: 'source-over', lineWidth: 1, lineCap: 'butt' }
  const gradient = { addColorStop(_offset: number, color: string) { colors.push(color) } }
  const context = new Proxy(state, {
    get(target, prop, receiver) {
      if (prop === 'createRadialGradient') return () => { radial++; return gradient }
      if (prop === 'createLinearGradient') return () => gradient
      if (prop === 'arc') return (x: number, y: number) => { arcs.push({ x, y }) }
      if (typeof prop === 'string' && !(prop in target)) return () => {}
      return Reflect.get(target, prop, receiver)
    },
    set(target, prop, value, receiver) {
      if ((prop === 'fillStyle' || prop === 'strokeStyle') && typeof value === 'string') colors.push(value)
      return Reflect.set(target, prop, value, receiver)
    },
  })
  return { context: context as unknown as CanvasRenderingContext2D, colors, arcs, radials: () => radial }
}

const cue = (kind: string, extra: Partial<SceneFx> = {}) => parseSceneFx([{ id: kind, kind, start: 0, end: 2.5, x: 50, y: 30, size: 120, intensity: .8, color: '#ffd56a', seed: 3, ...extra }])[0]

/** Hue (degrees) and saturation of an `rgba(...)` colour, or null for one that adds no light. */
function hueOf(color: string) {
  const match = color.match(/^rgba\((\d+), (\d+), (\d+), ([\d.]+)\)$/)
  if (!match || Number(match[4]) <= .01) return null
  const [r, g, b] = [1, 2, 3].map(index => Number(match[index]) / 255)
  const high = Math.max(r, g, b), low = Math.min(r, g, b)
  const hue = (Math.atan2(Math.sqrt(3) * (g - b), 2 * r - g - b) * 180 / Math.PI + 360) % 360
  return { hue, saturation: high ? (high - low) / high : 0 }
}

test('the shockwave front eases out, lights up at once, fades to nothing and leaves its echoes behind', () => {
  const wave = cue('shockwave')
  const radius = (time: number) => shockwaveState(wave, time).front.radius
  const samples = [0, .3, .6, .9, 1.2, 1.5, 1.8, 2.1, 2.5].map(radius)
  assert.ok(samples.every((value, index) => index === 0 || value > samples[index - 1]), 'the front only spreads')
  assert.ok(radius(1.25) - radius(0) > 3 * (radius(2.5) - radius(1.25)), 'most of the way in the first half: an ease out')
  assert.equal(radius(2.5), SHOCK_REACH)
  assert.equal(shockwaveState(wave, 0).front.light, 0)
  assert.ok(shockwaveState(wave, .1).front.light > .9, 'lit within a tenth of a second')
  assert.ok(shockwaveState(wave, 2.45).front.light < .02, 'and gone by the end')
  const late = shockwaveState(wave, 1)
  assert.equal(late.echoes.length, 2)
  assert.ok(late.echoes.every(echo => echo.radius < late.front.radius && echo.light < late.front.light))
  assert.ok(shockwaveState(wave, .02).flash > .3 && shockwaveState(wave, .7).flash < .05, 'the flash where it starts dies quickly')
  assert.ok(shockwaveState(cue('shockwave', { intensity: 1.6 }), 1).power > late.power)
})

test('light keeps the cue colour: gold stays gold in every layer, from the soft edge to the hot core', () => {
  for (const color of ['#ffd56a', '#77ddff']) {
    const target = hueOf(`rgba(${[1, 3, 5].map(offset => parseInt(color.slice(offset, offset + 2), 16)).join(', ')}, 1)`)!.hue
    for (const [kind, times] of [['shockwave', [.05, .5, 1.4, 2.3]], ['shield', [.3, 4, 12, 29.8]], ['embers', [.5, 1.5]]] as const) {
      const { context, colors } = recorder()
      const placed = cue(kind, { color, ...(kind === 'shield' ? { end: 30, size: 70, intensity: .4 } : {}) })
      for (const time of times) paintSceneFx(context, 640, 360, time, [placed])
      const lit = colors.map(hueOf).filter(value => value && value.saturation > .08)
      assert.ok(lit.length > 20, `${kind} paints in colour`)
      for (const value of lit) assert.ok(Math.abs(value!.hue - target) < 3, `${kind} ${color}: hue ${value!.hue.toFixed(1)} is not ${target.toFixed(1)}`)
    }
  }
  // The deeper edge and the whiter core keep the hue too.
  assert.deepEqual(richer([255, 213, 106], 1.5), [255, 192, 31.5])
  assert.deepEqual(whiter([255, 213, 106], .5), [255, 234, 180.5])
})

test('a shield reads at a low intensity and stays a glow, never an opaque disc', () => {
  const aura = parseSceneFx([{ id: 'aura', kind: 'shield', start: 0, end: 30, x: 52, y: 50, size: 70, intensity: .4, color: '#ffd56a' }])[0]
  const settled = shieldState(aura, 12)
  assert.ok(settled.light * settled.power > .5, 'intensity 0.4 still lights the rim')
  assert.ok(shieldState(aura, .05).light < .05 && shieldState(aura, 29.99).light < .05, 'it swells in and fades out')
  assert.ok(shieldBody(0) < shieldBody(.5) && shieldBody(.5) < shieldBody(.95), 'brighter toward the rim, as a bubble')
  assert.ok(shieldBody(1) <= .25, 'the body never covers what is inside it')
  const breaths = [0, 1, 2, 3].map(second => shieldState(aura, 10 + second).radius)
  assert.ok(Math.max(...breaths) - Math.min(...breaths) > .005, 'it breathes')
})

test('shockwave and shield are painted on the 2D frame instead of the filmed 3D sprite', () => {
  for (const kind of ['shockwave', 'shield', 'laser', 'rain', 'smoke']) assert.equal(drawnOnFrame(kind), true, kind)
  for (const kind of ['portal', 'energy_orb', 'fire']) assert.equal(drawnOnFrame(kind), false, kind)
  const { context, radials } = recorder()
  paintSceneFx(context, 640, 360, 1, [cue('shockwave'), cue('shield', { end: 30 })])
  assert.ok(radials() > 20, 'soft light, not a stroked ellipse')
})

test('particles drift across their box on their own: embers, stars and bubbles no longer line up on diagonals', () => {
  // Points on a few diagonal stripes have y nearly a function of x: neighbours across the box sit at
  // nearly the same height. Independent heights jump about a third of their range between neighbours.
  const jumps = (points: Arc[]) => {
    const seen = new Map(points.map(point => [`${point.x.toFixed(4)},${point.y.toFixed(4)}`, point]))
    const sorted = [...seen.values()].sort((a, b) => a.x - b.x), ys = sorted.map(point => point.y)
    const steps = sorted.slice(1).map((point, index) => Math.abs(point.y - sorted[index].y))
    return steps.reduce((sum, step) => sum + step, 0) / steps.length / (Math.max(...ys) - Math.min(...ys))
  }
  for (const kind of ['embers', 'stars', 'bubbles']) {
    for (const time of [.3, 1.2, 2.5]) {
      const { context, arcs } = recorder()
      paintSceneFx(context, 640, 360, time, [cue(kind, { end: 3, intensity: 1 })])
      assert.ok(arcs.length > 40, kind)
      assert.ok(jumps(arcs) > .2, `${kind} at ${time} s: neighbours jump ${jumps(arcs).toFixed(2)} of the height`)
    }
  }
})
