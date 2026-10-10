import assert from 'node:assert/strict'
import test from 'node:test'
import { pixelsLookBlank } from '../src/components/MainContent/videoFrameCapture.ts'

test('a black sample is blank and a drawn pixel is not', () => {
  assert.equal(pixelsLookBlank(new Uint8ClampedArray([0, 0, 0, 255, 4, 4, 4, 255])), true)
  const drawn = new Uint8ClampedArray([0, 0, 0, 255, 20, 40, 80, 255])
  assert.equal(pixelsLookBlank(drawn), false)
  assert.equal(pixelsLookBlank(new Uint8ClampedArray()), true)
})
