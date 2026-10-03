import assert from 'node:assert/strict'
import test from 'node:test'
import { startWorld3DExport } from '../src/features/scene3d/exportLock.ts'
import { DRAFT_RENDER, FrameAccumulator, MAX_SUPERSAMPLED_SIDE, NO_MOTION_BLUR, motionBlurOf, renderQualityOf, subframeTimes, supersampledSize } from '../src/features/scene3d/exportQuality.ts'
import { applyScene3DTemplate } from '../src/features/scene3d/templates.ts'

test('a plan without quality fields renders as draft', () => {
  assert.deepEqual(renderQualityOf({ width: 1920, height: 1080 }), DRAFT_RENDER)
  assert.deepEqual(renderQualityOf(undefined), DRAFT_RENDER)
  assert.deepEqual(renderQualityOf({ supersample: 'big', samples: -2 }), DRAFT_RENDER)
})

test('final and master plans map to supersampling and MSAA within bounds', () => {
  assert.deepEqual(renderQualityOf({ supersample: 1.5, samples: 4 }), { supersample: 1.5, samples: 4 })
  assert.deepEqual(renderQualityOf({ supersample: 9, samples: 32 }), { supersample: 4, samples: 8 })
})

test('the supersampled size keeps even dimensions and the aspect', () => {
  assert.deepEqual(supersampledSize({ width: 1920, height: 1080 }, 1), { width: 1920, height: 1080 })
  assert.deepEqual(supersampledSize({ width: 1920, height: 1080 }, 2), { width: 3840, height: 2160 })
  assert.deepEqual(supersampledSize({ width: 1920, height: 1080 }, 1.5), { width: 2880, height: 1620 })
  assert.deepEqual(supersampledSize({ width: 1080, height: 1920 }, 1.5), { width: 1620, height: 2880 })
  assert.deepEqual(supersampledSize({ width: 3840, height: 2160 }, 2), { width: 7680, height: 4320 })
  const capped = supersampledSize({ width: 5120, height: 2880 }, 2)
  assert.equal(capped.width, MAX_SUPERSAMPLED_SIDE)
  assert.equal(capped.width % 2 + capped.height % 2, 0)
})

test('a supersampled export paints larger and forwards the render quality to the stage', () => {
  const calls: unknown[] = []
  const handle = {
    beginExport() { calls.push('begin') },
    setExportSize(width: number, height: number) { calls.push(['size', width, height]) },
    setExportQuality(enabled: boolean, render?: unknown) { calls.push(['quality', enabled, render]) },
  }
  startWorld3DExport(handle, applyScene3DTemplate('drive-chase'), { width: 1280, height: 720 }, { supersample: 2, samples: 4 })
  assert.deepEqual(calls, ['begin', ['size', 2560, 1440], ['quality', true, { supersample: 2, samples: 4 }]])
  calls.length = 0
  startWorld3DExport(handle, applyScene3DTemplate('drive-chase'), { width: 1280, height: 720 })
  assert.deepEqual(calls, ['begin', ['size', 1280, 720], ['quality', true, DRAFT_RENDER]])
})

test('a plan without blur fields stays one sharp frame', () => {
  assert.deepEqual(motionBlurOf({ width: 64 }), NO_MOTION_BLUR)
  assert.deepEqual(motionBlurOf({ subframes: 8, shutter: 0 }), NO_MOTION_BLUR)
  assert.deepEqual(motionBlurOf({ subframes: 1, shutter: 180 }), NO_MOTION_BLUR)
  assert.deepEqual(motionBlurOf({ subframes: 64, shutter: 720 }), { subframes: 16, shutter: 360 })
})

test('subframes sample the open shutter from the frame time and never pass the end', () => {
  const frame = 1 / 24
  const times = subframeTimes(1, { subframes: 4, shutter: 180 }, frame, 10)
  assert.equal(times.length, 4)
  assert.ok(times.every(t => t > 1 && t < 1 + frame / 2))
  assert.ok(Math.abs(times[0] - (1 + frame / 16)) < 1e-12 && Math.abs(times[3] - (1 + 7 * frame / 16)) < 1e-12)
  assert.deepEqual(subframeTimes(9.99, { subframes: 2, shutter: 360 }, frame, 10).map(t => t <= 10), [true, true])
  assert.deepEqual(subframeTimes(2, NO_MOTION_BLUR, frame, 10), [2])
})

test('identical subframes average to the same pixels; light adds up linearly', () => {
  const pixel = (r: number, g: number, b: number) => Uint8ClampedArray.from([r, g, b, 255])
  const same = new FrameAccumulator(4)
  for (let i = 0; i < 8; i++) same.add(pixel(17, 128, 250))
  assert.deepEqual(Array.from(same.result()), [17, 128, 250, 255])
  const mixed = new FrameAccumulator(4)
  mixed.add(pixel(0, 0, 0)); mixed.add(pixel(255, 255, 255))
  assert.deepEqual(Array.from(mixed.result()), [188, 188, 188, 255], 'half black, half white is 50 % light, sRGB 188')
  assert.throws(() => mixed.add(new Uint8ClampedArray(8)), /size/)
})

test('every 8-bit value survives the linear round trip within one step', () => {
  for (let value = 0; value < 256; value++) {
    const one = new FrameAccumulator(4)
    one.add(Uint8ClampedArray.from([value, value, value, 255]))
    assert.ok(Math.abs(one.result()[0] - value) <= 1, `value ${value}`)
  }
})
