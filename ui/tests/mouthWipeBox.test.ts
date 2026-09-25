import assert from 'node:assert/strict'
import test from 'node:test'
import { mouthWipeBox, resizeMouthWipeBox } from '../src/features/characters/mouthWipeBox'
import { wipeMouthRegion } from '../src/lib/characterKitFaceRig'

test('a horizontal corner drag widens the mouth eraser without increasing its height', () => {
  const anchor = { offsetX: 0, offsetY: -18, scale: .08, rotation: 0 }
  const box = mouthWipeBox(anchor)
  const resized = resizeMouthWipeBox(box, 20, 5)
  assert.deepEqual(mouthWipeBox(resized.anchor, resized.aspect), { ...box, width: 20, height: 5 })
  const moved = mouthWipeBox({ ...resized.anchor, offsetX: resized.anchor.offsetX + 3 }, resized.aspect)
  assert.equal(moved.width, 20); assert.equal(moved.height, 5); assert.equal(moved.x, box.x + 3)
})

test('rectangular wiping covers the painted mouth corners and leaves nearby facial features intact', () => {
  const width = 60, height = 30, rgba = new Uint8ClampedArray(width * height * 4)
  for (let index = 0; index < rgba.length; index += 4) rgba.set([230, 180, 140, 255], index)
  const ink = (x: number, y: number) => rgba.set([20, 20, 20, 255], (y * width + x) * 4)
  ink(14, 13); ink(30, 15); ink(46, 17); ink(30, 5)
  const result = wipeMouthRegion(rgba, width, height, { cx: 30, cy: 15, rx: 20, ry: 4, shape: 'rectangle' })
  for (const [x, y] of [[14, 13], [30, 15], [46, 17]]) assert.ok(result[(y * width + x) * 4] > 150)
  assert.equal(result[(5 * width + 30) * 4], 20)
  assert.equal(rgba[(15 * width + 30) * 4], 20)
})
