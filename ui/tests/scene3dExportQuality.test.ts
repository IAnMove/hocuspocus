import assert from 'node:assert/strict'
import test from 'node:test'
import { startWorld3DExport } from '../src/features/scene3d/exportLock.ts'
import { DRAFT_RENDER, MAX_SUPERSAMPLED_SIDE, renderQualityOf, supersampledSize } from '../src/features/scene3d/exportQuality.ts'
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
