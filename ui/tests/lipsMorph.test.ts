import assert from 'node:assert/strict'
import test from 'node:test'
import { interpolateMouthMesh, mouthContourMesh, mouthTriangleTransform } from '../src/lib/lipsMorph'

function ellipse(rx: number, ry: number) {
  const size = 96, data = new Uint8ClampedArray(size * size * 4)
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) {
    if (((x - 48) / rx) ** 2 + ((y - 48) / ry) ** 2 <= 1) data[(y * size + x) * 4 + 3] = 255
  }
  return data
}

test('transparent mouth contours produce intermediate geometry rather than two unchanged outlines', () => {
  const closed = mouthContourMesh(ellipse(36, 6), 96, 96)!, open = mouthContourMesh(ellipse(24, 30), 96, 96)!
  assert.ok(closed); assert.ok(open)
  assert.deepEqual(interpolateMouthMesh(closed, open, 0), closed)
  assert.deepEqual(interpolateMouthMesh(closed, open, 1), open)
  const halfway = interpolateMouthMesh(closed, open, .5)
  const column = Math.floor(closed.columns / 2) * closed.rows
  assert.ok(halfway.points[column + 1].y < closed.points[column + 1].y)
  assert.ok(halfway.points[column + 1].y > open.points[column + 1].y)
  assert.ok(halfway.points[column + 3].y > closed.points[column + 3].y)
  assert.ok(halfway.points[column + 3].y < open.points[column + 3].y)
  assert.ok(halfway.points.every(point => Number.isFinite(point.x) && Number.isFinite(point.y)))
})

test('empty and opaque background images do not claim to be deformable mouths', () => {
  assert.equal(mouthContourMesh(new Uint8ClampedArray(96 * 96 * 4), 96, 96), undefined)
  assert.equal(mouthContourMesh(new Uint8ClampedArray(96 * 96 * 4).fill(255), 96, 96), undefined)
})

test('the affine warp lands every vertex on its target, including translated and skewed triangles', () => {
  const source = [{ x: 4, y: 7 }, { x: 20, y: 10 }, { x: 5, y: 30 }]
  const target = [{ x: 9, y: 1 }, { x: 32, y: 14 }, { x: 3, y: 44 }]
  const [a, b, c, d, e, f] = mouthTriangleTransform(source, target)!
  for (let index = 0; index < 3; index++) {
    const { x, y } = source[index]
    assert.ok(Math.abs(a * x + c * y + e - target[index].x) < 1e-9)
    assert.ok(Math.abs(b * x + d * y + f - target[index].y) < 1e-9)
  }
  assert.equal(mouthTriangleTransform([{ x: 0, y: 0 }, { x: 0, y: 1 }, { x: 0, y: 2 }], target), undefined)
})
