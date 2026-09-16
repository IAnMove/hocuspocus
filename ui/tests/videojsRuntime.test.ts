import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import vm from 'node:vm'
import { DEFAULT_VIDEOJS_THEME, createVideoJsDocument, createVideoJsScene } from '../src/features/videojs/document.ts'
import { videoJsExampleDocument } from '../src/features/videojs/examples.ts'
import { VIDEOJS_KIT_REFERENCE } from '../src/features/videojs/promptGuide.ts'
import { videoJsRenderSpec } from '../src/features/videojs/sandbox.ts'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '../src/features/videojs/runtime')
const WORKER = readFileSync(join(ROOT, 'videojsWorker.js'), 'utf8')
const HOST = readFileSync(join(ROOT, 'videojsHost.js'), 'utf8')

type Message = Record<string, unknown>

/** A 2D context that accepts every call and records the ones scenes rely on. */
function fakeContext(canvas: FakeCanvas) {
  const calls: string[] = []
  const gradient = { addColorStop: () => undefined }
  const base: Record<string, unknown> = {
    canvas,
    measureText: (text: string) => ({ width: String(text).length * 10 }),
    createLinearGradient: () => gradient,
    createRadialGradient: () => gradient,
    createPattern: () => ({}),
    createImageData: (w: number, h: number) => ({ data: new Uint8ClampedArray(w * h * 4) }),
  }
  return {
    calls,
    context: new Proxy(base, {
      get(target, key) {
        if (key in target) return target[key as string]
        return (...args: unknown[]) => { calls.push(String(key)); return args.length ? undefined : undefined }
      },
      set(target, key, value) { target[key as string] = value; return true },
    }),
  }
}

class FakeCanvas {
  width: number
  height: number
  record = fakeContext(this)
  constructor(width: number, height: number) { this.width = width; this.height = height }
  getContext() { return this.record.context }
  transferToImageBitmap() { return { width: this.width, height: this.height, draws: this.record.calls.length } }
}

function loadRuntime() {
  const messages: Message[] = []
  const module = { exports: {} as Record<string, (...args: never[]) => unknown> }
  const context: Record<string, unknown> = {
    module, OffscreenCanvas: FakeCanvas, postMessage: (message: Message) => messages.push(message), console,
  }
  context.self = context
  vm.createContext(context)
  vm.runInContext(WORKER, context, { filename: 'videojsWorker.js' })
  const send = (data: Message) => (context.onmessage as (event: { data: Message }) => void)({ data })
  // Values created inside the vm realm have foreign prototypes; compare plain copies.
  const plain = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T
  return { api: module.exports, context, messages, send, plain }
}

test('kit easing, timing and randomness are deterministic', () => {
  const { api, plain } = loadRuntime()
  const ease = api.ease as unknown as Record<string, (x: number) => number>
  for (const [name, fn] of Object.entries(ease)) {
    assert.ok(Math.abs(fn(0)) < 1e-9, `${name}(0)`)
    assert.ok(Math.abs(fn(1) - 1) < 1e-9, `${name}(1)`)
  }
  const tween = api.tween as unknown as (t: number, s: number, d: number, e?: string) => number
  assert.equal(tween(0, 1, 1), 0)
  assert.equal(tween(5, 1, 1), 1)
  assert.equal(tween(1.5, 1, 1, 'linear'), 0.5)
  assert.equal(tween(2, 2, 0), 1)
  const keyframes = api.keyframes as unknown as (t: number, frames: unknown[]) => unknown
  assert.equal(keyframes(-1, [[0, 10], [1, 20, 'linear']]), 10)
  assert.equal(keyframes(0.5, [[1, 20, 'linear'], [0, 10]]), 15)
  assert.deepEqual(plain(keyframes(0.5, [[0, [0, 10]], [1, [10, 20], 'linear']])), [5, 15])
  const random = api.random as unknown as (seed: unknown) => () => number
  const a = random('scene'); const b = random('scene')
  const values = Array.from({ length: 5 }, () => a())
  assert.deepEqual(values, Array.from({ length: 5 }, () => b()))
  assert.ok(values.every(value => value >= 0 && value < 1))
  const noise = api.noise as unknown as (x: number, seed?: number) => number
  assert.equal(noise(3.25, 1), noise(3.25, 1))
  assert.ok(Array.from({ length: 50 }, (_, i) => noise(i / 7)).every(value => value >= -1 && value <= 1))
  const color = api.color as unknown as Record<string, (...args: unknown[]) => string>
  assert.equal(color.mix('#000000', '#ffffff', 0.5), 'rgba(128, 128, 128, 1)')
  assert.equal(color.alpha('#ff000080', 0.5), 'rgba(255, 0, 0, 0.251)')
})

test('every kit API documented for the LLM exists in the runtime', () => {
  const { api } = loadRuntime()
  const kit = (api.createKit as unknown as (env: unknown) => Record<string, Record<string, unknown>>)({ width: 1920, height: 1080, fps: 30, theme: DEFAULT_VIDEOJS_THEME })
  const lines = VIDEOJS_KIT_REFERENCE.split('\n').filter(line => line.startsWith('- ') && !/^- (2d|3d):/.test(line))
  const members: string[] = []
  const topLevel = ['theme', 'TAU']
  for (const line of lines) {
    for (const [, group, list, single] of line.matchAll(/\b(math|ease|color|text|layout|draw|three)\.(?:\{([^}]+)\}|([a-zA-Z]+))/g)) {
      for (const name of list ? list.replace(/\([^)]*\)/g, '').split(',').map(item => item.trim()) : [single]) members.push(`${group}.${name}`)
    }
    for (const [, name] of line.replace(/\{[^}]*\}/g, '').matchAll(/(?:^- |, )([a-zA-Z]+)(?=\()/g)) topLevel.push(name)
  }
  for (const name of topLevel) assert.ok(name in kit, `kit.${name}`)
  for (const path of members) {
    const [group, name] = path.split('.')
    assert.ok(name in kit[group], `kit.${path}`)
  }
  assert.ok(members.length > 40, `checked ${members.length} members`)
  assert.ok(topLevel.includes('keyframes') && topLevel.includes('font'))
})

test('determinism guards freeze clocks and disable timers and network', () => {
  const { context } = loadRuntime()
  const math = vm.runInContext('Math', context) as Math
  const date = vm.runInContext('Date', context) as DateConstructor
  assert.equal(date.now(), 0)
  assert.equal(typeof math.random(), 'number')
  assert.throws(() => (context.setTimeout as () => void)(), /render\(\{ t \}\)/)
  assert.throws(() => (context.requestAnimationFrame as () => void)(), /disabled/)
  return assert.rejects((context.fetch as () => Promise<unknown>)(), /Network access is disabled/)
})

test('the 2D demo scenes load and render frames without errors, deterministically', () => {
  const demo = videoJsExampleDocument()
  const document = { ...demo, width: 640, height: 360, scenes: demo.scenes.filter(scene => scene.kind === '2d') }
  const run = () => {
    const runtime = loadRuntime()
    runtime.send({ type: 'init', document: videoJsRenderSpec(document), three: null })
    const ready = runtime.plain(runtime.messages.find(message => message.type === 'ready'))
    assert.deepEqual(ready?.errors, [])
    const frames = [0, 0.3, 2.1, 4.2, 6.5, 9.4, 13.2, 16.9].map((time, index) => {
      runtime.send({ type: 'frame', id: index, time })
      const frame = runtime.plain(runtime.messages.filter(message => message.type === 'frame').at(-1))
      assert.equal(frame?.id, index)
      assert.deepEqual(frame?.errors, [], `frame at ${time}s`)
      return (frame?.bitmap as { draws: number }).draws
    })
    return frames
  }
  assert.deepEqual(run(), run())
})

test('scene failures are reported per scene with a code line, without stopping other scenes', () => {
  const document = createVideoJsDocument({
    width: 320,
    height: 180,
    scenes: [
      createVideoJsScene('2d', { id: 'syntax', code: 'return { render( }' }),
      createVideoJsScene('2d', { id: 'shape', code: 'return { draw() {} }' }),
      createVideoJsScene('2d', { id: 'throws', code: 'return {\n  render({ t }) {\n    if (t > 1) missing.value = 1\n  },\n}' }),
      createVideoJsScene('2d', { id: 'fine', code: 'export default { render({ ctx, kit }) { kit.draw.background(ctx) } }' }),
      createVideoJsScene('3d', { id: 'nothree' }),
    ],
  })
  const runtime = loadRuntime()
  runtime.send({ type: 'init', document: videoJsRenderSpec(document), three: null })
  const ready = runtime.plain(runtime.messages.find(message => message.type === 'ready')) as { errors: Array<{ sceneId: string; phase: string; message: string }> }
  assert.deepEqual(ready.errors.map(error => `${error.sceneId}:${error.phase}`), ['syntax:compile', 'shape:compile', 'nothree:setup'])
  assert.match(ready.errors[1].message, /must return an object with render/)
  runtime.send({ type: 'frame', id: 1, time: 8 + 2 })
  const frame = runtime.plain(runtime.messages.at(-1)) as { errors: Array<{ sceneId: string; phase: string; line?: number }> }
  assert.deepEqual(frame.errors.map(error => `${error.sceneId}:${error.phase}`), ['throws:render'])
  assert.equal(frame.errors[0].line, 3)
  runtime.send({ type: 'frame', id: 2, time: 12.5 })
  assert.deepEqual(runtime.plain(runtime.messages.at(-1) as { errors: unknown[] }).errors, [])
})

test('the iframe host only accepts messages from its parent and forwards frames', () => {
  assert.match(HOST, /event\.source !== parent/)
  assert.match(HOST, /worker\.terminate\(\)/)
  assert.match(HOST, /transfer/)
  assert.doesNotMatch(HOST, /allow-same-origin|localStorage|document\.cookie/)
})
