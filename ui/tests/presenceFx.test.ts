import assert from 'node:assert/strict'
import test from 'node:test'
import classes from '../../app/shared/scene_effect_classes.json' with { type: 'json' }
import { paintSceneFx } from '../src/features/sceneFx/paint.ts'
import { PRESENCE_KINDS, paintPresence, presenceLayers } from '../src/features/sceneFx/presence/index.ts'
import { presenceFrame, renderSize, visibleWindow } from '../src/features/sceneFx/presence/stage.ts'
import { FX_CATALOG, parseSceneFx } from '../src/features/sceneFx/types.ts'

const KINDS = [...PRESENCE_KINDS]
const cueOf = (kind: string, extra: Record<string, unknown> = {}) =>
  parseSceneFx([{ id: kind, kind, start: 0, end: 6, x: 50, y: 50, size: 80, intensity: 1, seed: 4, sound: false, ...extra }])[0]

/** A 2D context that counts what the 2D painters draw and answers the calls the painters make. */
function countingContext(width: number, height: number) {
  const calls: Record<string, number> = {}
  const state: Record<string, unknown> = { canvas: { width, height }, globalAlpha: 1, globalCompositeOperation: 'source-over', fillStyle: '#000', strokeStyle: '#000', lineWidth: 1, lineCap: 'butt', font: '10px monospace', textAlign: 'left', filter: 'none' }
  const context = new Proxy(state, {
    get(target, prop, receiver) {
      if (prop === 'createRadialGradient' || prop === 'createLinearGradient') return () => ({ addColorStop() {} })
      if (prop === 'measureText') return () => ({ width: 1 })
      if (prop === 'getTransform') return () => ({ a: 1, b: 0, c: 0, d: 1, e: 0, f: 0 })
      if (typeof prop === 'string' && !(prop in target)) return () => { calls[prop] = (calls[prop] ?? 0) + 1 }
      return Reflect.get(target, prop, receiver)
    },
  })
  return { context: context as unknown as CanvasRenderingContext2D, calls }
}

test('the ten presence effects drawn with Three.js keep their ids, their class and their shot-long default', () => {
  assert.ok(KINDS.length >= 10, `${KINDS.length} effects`)
  const sizes = { anime_aura: 'cover', shield: 'cover', fog: 'own', smoke: 'framing', dust: 'cover', stars: 'cover', aurora: 'cover', bubbles: 'cover', embers: 'cover', meteor_shower: 'cover' } as Record<string, string>
  for (const kind of KINDS) {
    assert.ok(FX_CATALOG.some(item => item.id === kind), `${kind} is in the catalog`)
    const entry = (classes.effects as Record<string, { class: string; size: string }>)[kind]
    assert.equal(entry.class, 'presence', `${kind} is a presence effect`)
    assert.equal(entry.size, sizes[kind], `${kind} keeps its size rule`)
  }
  assert.equal(classes.classes.presence.duration, 'shot')
  // A cue a script wrote years ago still parses to the same kind, size and seed: the painter is the only thing that changed.
  for (const kind of KINDS) assert.deepEqual(cueOf(kind, { size: 125, seed: 9 }), { ...cueOf(kind), size: 125, seed: 9 })
})

test('without WebGL every presence effect is painted by its 2D painter and nothing throws', () => {
  for (const kind of KINDS) {
    const cue = cueOf(kind)
    const probe = countingContext(320, 180)
    assert.equal(paintPresence(probe.context, cue, 1.5), false, `${kind}: no WebGL, no Three.js painter`)
    for (const time of [0.1, 1.5, 5.9]) {
      const { context, calls } = countingContext(320, 180)
      assert.doesNotThrow(() => paintSceneFx(context, 320, 180, time, [cue]), `${kind} @ ${time}`)
      assert.ok(Object.values(calls).reduce((sum, count) => sum + count, 0) > 0, `${kind} @ ${time} drew with the 2D painter`)
    }
  }
})

test('an effect that is not a presence effect never goes to the Three.js painter', () => {
  const { context } = countingContext(64, 64)
  for (const item of FX_CATALOG.filter(entry => !PRESENCE_KINDS.has(entry.id))) assert.equal(paintPresence(context, cueOf(item.id), 1), false, item.id)
  assert.deepEqual(KINDS.filter(kind => (classes.effects as Record<string, { class: string }>)[kind].class !== 'presence'), [])
})

test('every layer of every presence effect fades with the cue, hashes with integers and stays inside its pixel budget', () => {
  for (const kind of KINDS) {
    const layers = presenceLayers(kind)
    assert.ok(layers.length >= 1, kind)
    for (const { def, mesh } of layers) {
      const material = mesh.material, uniforms = Object.keys(material.uniforms)
      const source = `${material.vertexShader}\n${material.fragmentShader}`.replace(/\/\/.*$/gm, '')
      assert.match(material.fragmentShader, /uEnv/, `${kind}: the layer follows the fade in and out`)
      assert.doesNotMatch(source, /fract\(sin\(|sin\(dot\(/, `${kind}: no sine hash (it breaks into blocks on some GPUs)`)
      assert.doesNotMatch(source, /\b(half|fixed|long|short|sampler3D)\b/, `${kind}: no reserved GLSL word`)
      assert.match(material.fragmentShader, /gl_FragColor/, kind)
      for (const name of Object.keys(def.extra ?? {})) {
        assert.ok(uniforms.includes(name), `${kind}: ${name} is a uniform of the material`)
        assert.match(material.fragmentShader, new RegExp(`uniform [a-z0-9]+ [^;]*\\b${name}\\b`), `${kind}: ${name} is declared in the shader`)
      }
      assert.ok(def.maxPixels <= 1_000_000, `${kind}: ${def.maxPixels} pixels at most`)
      assert.ok(['add', 'over'].includes(def.blend) && ['lighter', 'source-over'].includes(def.composite), kind)
      assert.ok(!def.instances || def.instances <= 400, `${kind}: ${def.instances} instances`)
      // Additive light lands as light, a layer over the picture lands over it.
      assert.equal(def.blend === 'add', def.composite === 'lighter', kind)
    }
  }
})

test('the fade envelope runs on the wall clock, whatever the effect speed', () => {
  const { context } = countingContext(640, 360)
  const slow = cueOf('anime_aura', { speed: 0.05, end: 12 })
  const start = presenceFrame(context, slow, 0), middle = presenceFrame(context, slow, 6 * 0.05), end = presenceFrame(context, slow, 11.99 * 0.05)
  assert.equal(start.env, 0)
  assert.equal(middle.env, 1, 'a rain that hangs in the air is not faded out by its own slow clock')
  assert.ok(end.env < 0.05)
  assert.ok(Math.abs(middle.real - 6) < 1e-9)
  assert.deepEqual(presenceFrame(context, slow, 0.3).rgb.map(value => Math.round(value * 255)), [255, 227, 108], 'the cue colour, 0-1 channels')
})

/** A transform made of translate, scale and rotate, as `paintPlacedCue` builds it, with the two calls the stage makes on it. */
function matrix(x: number, y: number, scale: number, degrees = 0) {
  const turn = degrees * Math.PI / 180, a = Math.cos(turn) * scale, b = Math.sin(turn) * scale
  return {
    a, b, c: -b, d: a, e: x, f: y,
    inverse() {
      const det = a * a + b * b
      return { transformPoint: ({ x: px, y: py }: { x: number; y: number }) => ({ x: (a * (px - x) + b * (py - y)) / det, y: (-b * (px - x) + a * (py - y)) / det }) }
    },
  }
}
const windowFor = (transform: ReturnType<typeof matrix>, width = 1920, height = 1080, region?: readonly [number, number, number, number]) =>
  visibleWindow({ getTransform: () => transform, canvas: { width, height } } as unknown as CanvasRenderingContext2D, region)

test('a layer paints the part of its region that the frame shows, in cue units', () => {
  // size 80 on 1920 x 1080: 864 px per cue unit, the cue's middle in the middle of the frame.
  const seen = windowFor(matrix(960, 540, 864))!
  assert.ok(Math.abs(seen.scale - 864) < 1e-9)
  assert.deepEqual(seen.win.map(value => Math.round(value * 1000) / 1000), [-1.111, -.625, 1.111, .625])
  // A region smaller than the frame bounds it; a region off the frame leaves nothing to paint.
  assert.deepEqual(windowFor(matrix(960, 540, 864), 1920, 1080, [-.5, -.4, .5, .4])!.win, [-.5, -.4, .5, .4])
  assert.equal(windowFor(matrix(960, 540, 864), 1920, 1080, [3, 3, 4, 4]), null)
  // A cue turned a quarter turn: the frame is a taller window in the cue's own space.
  const turned = windowFor(matrix(960, 540, 864, 90))!.win
  assert.ok(Math.abs(turned[2] - turned[0] - 1080 / 864) < 1e-9 && Math.abs(turned[3] - turned[1] - 1920 / 864) < 1e-9)
  assert.equal(windowFor(matrix(0, 0, 0)), null)
})

test('a layer is rendered at the frame resolution, shrunk to its pixel budget with the same shape', () => {
  assert.deepEqual(renderSize([-1, -1, 1, 1], 400, 1_000_000), [800, 800])
  const [w, h] = renderSize([-1.111, -.625, 1.111, .625], 864, 520_000)
  assert.ok(w * h <= 520_000 * 1.01 && w * h >= 520_000 * .95, `${w} x ${h}`)
  assert.ok(Math.abs(w / h - 1.111 / .625) < 0.01, 'the aspect ratio holds')
  assert.deepEqual(renderSize([-1.111, -.625, 1.111, .625], 864, 520_000), [w, h], 'the same window, the same size')
  assert.deepEqual(renderSize([0, 0, .001, .001], 100, 1000), [2, 2])
})
