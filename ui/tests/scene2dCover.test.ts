import assert from 'node:assert/strict'
import test from 'node:test'
import { coverDrawState } from '../src/lib/scene2d/cover.ts'
import { createSceneEvaluator } from '../src/lib/scene2d/evaluate.ts'
import { normalizeScene2D } from '../src/lib/scene2d/normalize.ts'
import { paintScene2D } from '../src/lib/scene2d/paint.ts'
import type { AnimatorLayer, AnimatorScene, LayerState } from '../src/lib/scene2d/types.ts'

const BACKGROUND = [0x0b, 0x10, 0x20, 255] as const
const IMAGE = [220, 30, 40, 255] as const

function layer(overrides: Partial<AnimatorLayer> = {}): AnimatorLayer {
  const placed = { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 }
  return {
    id: 'clip', name: 'clip', type: 'image', source: '/api/v1/file/clip.png', visible: true, z: 0,
    transform: placed,
    animation: { start: { ...placed }, end: { ...placed }, duration: 4, curve: 'linear' },
    ...overrides,
  } as AnimatorLayer
}

function scene(frame: AnimatorLayer, width: number, height: number): AnimatorScene {
  return { version: 1, name: 'cover', width, height, fps: 24, duration: 4, layers: [frame] }
}

function state(partial: Partial<LayerState>): LayerState {
  return { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0, z: 0, ...partial }
}

type Solid = { width: number; height: number; rgba: readonly [number, number, number, number] }
type Rect = { x: number; y: number; w: number; h: number }

function overlaps(pixel: number, origin: number, size: number) {
  return pixel + 0.5 >= origin && pixel + 0.5 < origin + size
}

function paintSolid(target: Uint8ClampedArray, width: number, rect: Rect, color: readonly [number, number, number, number]) {
  if (rect.w <= 0 || rect.h <= 0) return
  for (let y = 0; y < target.length / 4 / width; y += 1) {
    if (!overlaps(y, rect.y, rect.h)) continue
    for (let x = 0; x < width; x += 1) {
      if (!overlaps(x, rect.x, rect.w)) continue
      const index = (y * width + x) * 4
      target[index] = color[0]
      target[index + 1] = color[1]
      target[index + 2] = color[2]
      target[index + 3] = color[3]
    }
  }
}

function intersect(current: Rect | null, next: Rect): Rect {
  if (!current) return next
  const x = Math.max(current.x, next.x)
  const y = Math.max(current.y, next.y)
  return { x, y, w: Math.min(current.x + current.w, next.x + next.w) - x, h: Math.min(current.y + current.h, next.y + next.h) - y }
}

function pixelContext(width: number, height: number) {
  const pixels = new Uint8ClampedArray(width * height * 4)
  let tx = 0
  let ty = 0
  let clip: Rect | null = null
  let path: Rect | null = null
  const stack: Array<{ tx: number; ty: number; clip: Rect | null }> = []
  const context = {
    canvas: { width, height },
    fillStyle: '#000000',
    globalAlpha: 1,
    globalCompositeOperation: 'source-over',
    filter: 'none',
    save() { stack.push({ tx, ty, clip }) },
    restore() {
      const previous = stack.pop()
      if (!previous) return
      tx = previous.tx
      ty = previous.ty
      clip = previous.clip
    },
    translate(x: number, y: number) { tx += x; ty += y },
    rotate(angle: number) { if (angle !== 0) throw new Error('cover pixel test only checks upright frames') },
    beginPath() { path = null },
    rect(x: number, y: number, w: number, h: number) { path = { x: x + tx, y: y + ty, w, h } },
    closePath() {},
    clip() { if (path) clip = intersect(clip, path) },
    fillRect(x: number, y: number, w: number, h: number) {
      const color = context.fillStyle === '#0b1020' ? BACKGROUND : [0, 0, 0, 255]
      paintSolid(pixels, width, intersect(clip, { x: x + tx, y: y + ty, w, h }), color)
    },
    drawImage(media: Solid, ...args: number[]) {
      const [dx, dy, dw, dh] = args.length === 8 ? args.slice(4) : args
      paintSolid(pixels, width, intersect(clip, { x: dx + tx, y: dy + ty, w: dw, h: dh }), media.rgba)
    },
    getImageData(x: number, y: number, w: number, h: number) {
      const data = new Uint8ClampedArray(w * h * 4)
      for (let row = 0; row < h; row += 1) {
        for (let col = 0; col < w; col += 1) {
          const from = ((y + row) * width + (x + col)) * 4
          const to = (row * w + col) * 4
          data.set(pixels.subarray(from, from + 4), to)
        }
      }
      return { data, width: w, height: h }
    },
  }
  const canvas = {
    width,
    height,
    getContext() { return context },
  }
  return { canvas: canvas as unknown as HTMLCanvasElement, pixels }
}

function paint(frame: AnimatorLayer, width: number, height: number, media: Solid) {
  const { canvas, pixels } = pixelContext(width, height)
  const current = scene(frame, width, height)
  const evaluator = createSceneEvaluator(current)
  assert.equal(paintScene2D(canvas, current, 0, evaluator, () => media as unknown as HTMLCanvasElement), true)
  return pixels
}

function corners(pixels: Uint8ClampedArray, width: number, height: number) {
  const at = (x: number, y: number) => {
    const index = (y * width + x) * 4
    return [pixels[index], pixels[index + 1], pixels[index + 2], pixels[index + 3]]
  }
  return [at(0, 0), at(width - 1, 0), at(0, height - 1), at(width - 1, height - 1)]
}

test('cover scale accounts for a 1280×704 source in a wider frame and for focus', () => {
  const wide = coverDrawState(1920, 720, 1280, 704, false, undefined, state({}))
  assert.ok(Math.abs(wide.scale - 22 / 15) < 1e-9)
  assert.equal(wide.x, 50)
  assert.equal(wide.y, 50)
  const panned = coverDrawState(200, 200, 100, 100, false, undefined, state({ x: 10, y: 50, scale: 0.5 }))
  assert.equal(panned.scale, 1.8)
  assert.equal(panned.x, 10)
  assert.equal(panned.y, 50)
  const focused = coverDrawState(200, 200, 100, 100, false, { x: 0, y: 0 }, state({ x: 100, y: 100, scale: 1 }))
  assert.equal(focused.scale, 1)
  assert.equal(focused.x, 50)
  assert.equal(focused.y, 50)
  const zoomed = coverDrawState(200, 200, 100, 100, false, { x: 50, y: 50 }, state({ scale: 3 }))
  assert.equal(zoomed.scale, 3)
  assert.equal(zoomed.x, 50)
})

test('cover paints image corners where zoom, pan, or aspect would show the frame', () => {
  const media: Solid = { width: 1280, height: 704, rgba: IMAGE }
  const wide = { x: 50, y: 50, scale: 1, opacity: 1, rotation: 0 }
  const aspect = layer({
    type: 'video',
    transform: wide,
    animation: { start: { ...wide }, end: { ...wide }, duration: 4, curve: 'linear' },
  })
  const open = corners(paint(aspect, 192, 72, media), 192, 72)
  assert.deepEqual(open, [BACKGROUND, BACKGROUND, BACKGROUND, BACKGROUND].map(item => [...item]))
  const coveredAspect = corners(paint({ ...aspect, cover: true }, 192, 72, media), 192, 72)
  assert.deepEqual(coveredAspect, [IMAGE, IMAGE, IMAGE, IMAGE].map(item => [...item]))

  const pushed = { x: 12, y: 88, scale: 0.45, opacity: 1, rotation: 0 }
  const pan = layer({
    transform: pushed,
    animation: { start: { ...pushed }, end: { ...pushed }, duration: 4, curve: 'linear' },
    focus: { x: 0, y: 100 },
  })
  const square: Solid = { width: 100, height: 100, rgba: IMAGE }
  const revealed = corners(paint(pan, 80, 80, square), 80, 80)
  assert.ok(revealed.some(pixel => pixel[0] === BACKGROUND[0] && pixel[1] === BACKGROUND[1]))
  const saved = pan.animation.start.scale
  const covered = corners(paint({ ...pan, cover: true }, 80, 80, square), 80, 80)
  assert.deepEqual(covered, [IMAGE, IMAGE, IMAGE, IMAGE].map(item => [...item]))
  assert.equal(pan.animation.start.scale, saved)
  const plain = paint(pan, 80, 80, square)
  const explicitOff = paint({ ...pan, cover: false }, 80, 80, square)
  assert.deepEqual(explicitOff, plain)
})

test('normalize keeps cover and leaves layers without it unchanged', () => {
  const kept = normalizeScene2D(scene(layer({ cover: true }), 320, 180))
  assert.equal(kept.layers[0].cover, true)
  const plain = normalizeScene2D(scene(layer(), 320, 180))
  assert.equal(plain.layers[0].cover, undefined)
})
