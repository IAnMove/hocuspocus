import assert from 'node:assert/strict'
import test from 'node:test'
import { fittedPicture } from '../src/features/scene3d/previewFit'

test('the picture is the largest scene ratio that fits the free box', () => {
  const wide = fittedPicture(1000, 600, 16, 9)
  assert.equal(wide.width, 1000)
  assert.equal(wide.height, 562.5)
  const tall = fittedPicture(1000, 600, 9, 16)
  assert.equal(tall.width, 337.5)
  assert.equal(tall.height, 600)
  const folded = fittedPicture(980, 540, 1920, 1080)
  assert.equal(folded.width, 960)
  assert.ok(folded.width >= 900)
  assert.equal(fittedPicture(0, 400, 16, 9).width, 0)
})
