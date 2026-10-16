import assert from 'node:assert/strict'
import test from 'node:test'
import { effectiveSubframes, estimateRender, formatEstimateAmount, serverLevel } from '../src/features/render/renderEstimate.ts'
import { FRAME_PAINT_ATTEMPTS, isBlankFrame, paintVisibleFrame, qualityPaintSize, qualitySampleTimes } from '../src/features/scene2d/qualityFrame.ts'

test('a one-minute master at 24 fps on CPU is about 38 minutes', () => {
  const estimate = estimateRender({ level: 'master', shutter: 180, width: 1920, height: 1080, fps: 24, duration: 60, device: 'cpu' })
  assert.equal(estimate.frames, 1440)
  assert.equal(estimate.subframes, 8)
  assert.ok(Math.abs(estimate.seconds - 38.4 * 60) < 1)
  const amount = formatEstimateAmount(estimate.seconds, estimate.bytes)
  assert.equal(amount.timeUnit, 'minutes')
  assert.equal(amount.time, '38.4')
  assert.equal(amount.sizeUnit, 'megabytes')
  assert.equal(amount.size, '300')
})

test('draft ignores the shutter and final with a closed shutter stays one frame', () => {
  assert.equal(effectiveSubframes('draft', 180), 1)
  assert.equal(effectiveSubframes('final', 0), 1)
  assert.equal(effectiveSubframes('master', 90), 8)
  assert.equal(serverLevel({ level: 'draft', shutter: 180 }), null)
  assert.equal(serverLevel({ level: 'final', shutter: 90 }), 'final')
  const sharp = estimateRender({ level: 'final', shutter: 0, width: 1920, height: 1080, fps: 24, duration: 1, device: 'gpu' })
  const blurred = estimateRender({ level: 'final', shutter: 180, width: 1920, height: 1080, fps: 24, duration: 1, device: 'gpu' })
  assert.ok(sharp.seconds < blurred.seconds)
})

test('a draft video 2d plan paints once at the output size', () => {
  const plan = { width: 64, height: 36, fps: 24 }
  assert.deepEqual(qualitySampleTimes(plan, 0.5, 1), [0.5])
  assert.deepEqual(qualityPaintSize(plan), { width: 64, height: 36 })
})

test('final video 2d samples the open shutter and paints larger', () => {
  const plan = { width: 640, height: 360, fps: 24, supersample: 1.5, subframes: 4, shutter: 180 }
  const times = qualitySampleTimes(plan, 0, 1)
  assert.equal(times.length, 4)
  assert.ok(times[0] > 0 && times[3] < 1 / 24)
  const size = qualityPaintSize(plan)
  assert.ok(size.width > 640 && size.height > 360)
})

const rgba = (red: number, green: number, blue: number, alpha: number, pixels = 4) =>
  Uint8ClampedArray.from({ length: pixels * 4 }, (_unused, index) => [red, green, blue, alpha][index % 4])

test('a lost canvas (RGBA zeros) is blank, but a fade to opaque black is not', () => {
  assert.equal(isBlankFrame(rgba(0, 0, 0, 0)), true)
  assert.equal(isBlankFrame(rgba(0, 0, 0, 255)), false)
  assert.equal(isBlankFrame(rgba(11, 16, 32, 255)), false)
  const lastPixel = rgba(0, 0, 0, 0)
  lastPixel[lastPixel.length - 1] = 255
  assert.equal(isBlankFrame(lastPixel), false)
})

test('a blank readback is painted once more on a fresh canvas and the second picture is kept', async () => {
  const attempts: number[] = []
  const frame = await paintVisibleFrame(6.7083, async attempt => {
    attempts.push(attempt)
    return attempt === 0 ? { frame: 'lost', pixels: rgba(0, 0, 0, 0) } : { frame: 'painted', pixels: rgba(11, 16, 32, 255) }
  })
  assert.equal(frame, 'painted')
  assert.deepEqual(attempts, [0, 1])
})

test('a frame that reads back valid is painted once, even when it is opaque black', async () => {
  let paints = 0
  const frame = await paintVisibleFrame(0, async () => { paints += 1; return { frame: 'fade', pixels: rgba(0, 0, 0, 255) } })
  assert.equal(frame, 'fade')
  assert.equal(paints, 1)
})

test('a frame that stays blank stops the export and names its time', async () => {
  let paints = 0
  await assert.rejects(
    paintVisibleFrame(6.7083, async () => { paints += 1; return { frame: 'lost', pixels: rgba(0, 0, 0, 0) } }),
    /Video 2D frame at 6\.708 s came out blank/,
  )
  assert.equal(paints, FRAME_PAINT_ATTEMPTS)
})
