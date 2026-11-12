import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import { applyEtching } from '../src/features/sceneFx/etchingPaint.ts'
import { heldFrameTime, motionStepOf, shiftHeldFrame } from '../src/features/stopMotion.ts'

function plate(width: number, height: number, fill: (x: number, y: number) => number) {
  const pixels = new Uint8ClampedArray(width * height * 4)
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const i = (y * width + x) * 4
      const value = fill(x, y)
      pixels[i] = value
      pixels[i + 1] = value
      pixels[i + 2] = value
      pixels[i + 3] = 255
    }
  }
  return pixels
}

function inkCount(pixels: Uint8ClampedArray) {
  let count = 0
  for (let i = 0; i < pixels.length; i += 4) if (pixels[i] < 100) count += 1
  return count
}

test('etching is stable and a dark plate takes more ink than a light one', () => {
  const source = plate(32, 24, (x, y) => (x * 7 + y * 13) % 256)
  const once = source.slice()
  const twice = source.slice()
  applyEtching(once, 32, 24)
  applyEtching(twice, 32, 24)
  assert.deepEqual(once, twice)
  assert.equal(createHash('sha1').update(once).digest('hex').slice(0, 12), 'c3313e91b768')
  const dark = plate(32, 24, () => 10)
  const light = plate(32, 24, () => 250)
  applyEtching(dark, 32, 24)
  applyEtching(light, 32, 24)
  assert.ok(inkCount(dark) > inkCount(light))
})

test('motionStep 2 holds frames in pairs and an absent step leaves time alone', () => {
  const held = Array.from({ length: 8 }, (_, frame) => heldFrameTime(frame / 24, 24, 2))
  assert.deepEqual(held, [0, 0, 2 / 24, 2 / 24, 4 / 24, 4 / 24, 6 / 24, 6 / 24])
  for (let frame = 0; frame < 8; frame += 1) assert.equal(heldFrameTime(frame / 24, 24, null), frame / 24)
  assert.equal(motionStepOf(undefined), null)
  assert.equal(motionStepOf(5), null)
  assert.equal(motionStepOf(2), 2)
})

test('a zero offset does not read the frame back', () => {
  let reads = 0
  const ctx = {
    getImageData() { reads += 1; return { data: new Uint8ClampedArray(16) } },
    putImageData() {},
    fillRect() {},
    fillStyle: '',
  } as unknown as CanvasRenderingContext2D
  shiftHeldFrame(ctx, 2, 2, { x: 0, y: 0 })
  assert.equal(reads, 0)
})
