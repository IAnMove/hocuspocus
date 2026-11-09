import test from 'node:test'
import assert from 'node:assert/strict'
import { IMAGE_TRANSFORMS, transformImage, transformRect, transformedSize, type ImageTransform } from '../src/lib/imageTransform'

const rect = { x: 10, y: 5, width: 20, height: 10 }
const SIZE = { width: 100, height: 50 }

/** A canvas that records where the picture lands: the 2D matrix after translate/rotate/scale. */
function fakeCanvas() {
  let a = 1, b = 0, c = 0, d = 1, e = 0, f = 0
  const drawn: Array<{ x: number; y: number }[]> = []
  const context = {
    translate(tx: number, ty: number) { e += a * tx + c * ty; f += b * tx + d * ty },
    rotate(angle: number) {
      const cos = Math.cos(angle), sin = Math.sin(angle)
      const na = a * cos + c * sin, nb = b * cos + d * sin
      c = -a * sin + c * cos; d = -b * sin + d * cos; a = na; b = nb
    },
    scale(sx: number, sy: number) { a *= sx; b *= sx; c *= sy; d *= sy },
    drawImage(image: { naturalWidth: number; naturalHeight: number }) {
      const at = (x: number, y: number) => ({ x: Math.round(a * x + c * y + e), y: Math.round(b * x + d * y + f) })
      drawn.push([at(0, 0), at(image.naturalWidth, image.naturalHeight)])
    },
  }
  const canvas = { width: 0, height: 0, getContext: () => context }
  return { canvas, drawn, at: (x: number, y: number) => ({ x: Math.round(a * x + c * y + e), y: Math.round(b * x + d * y + f) }) }
}

function withFakeDocument<T>(canvas: unknown, run: () => T): T {
  const prior = Object.getOwnPropertyDescriptor(globalThis, 'document')
  Object.defineProperty(globalThis, 'document', { configurable: true, value: { createElement: () => canvas } })
  try { return run() } finally {
    if (prior) Object.defineProperty(globalThis, 'document', prior); else Reflect.deleteProperty(globalThis, 'document')
  }
}

test('a quarter turn swaps the size and a mirror keeps it', () => {
  assert.deepEqual(transformedSize(100, 50, 'rotateLeft'), { width: 50, height: 100 })
  assert.deepEqual(transformedSize(100, 50, 'rotateRight'), { width: 50, height: 100 })
  assert.deepEqual(transformedSize(100, 50, 'flipHorizontal'), { width: 100, height: 50 })
  assert.deepEqual(transformedSize(100, 50, 'flipVertical'), { width: 100, height: 50 })
})

test('the selected area follows the picture through each change', () => {
  assert.deepEqual(transformRect(rect, SIZE.width, SIZE.height, 'rotateRight'), { x: 35, y: 10, width: 10, height: 20 })
  assert.deepEqual(transformRect(rect, SIZE.width, SIZE.height, 'rotateLeft'), { x: 5, y: 70, width: 10, height: 20 })
  assert.deepEqual(transformRect(rect, SIZE.width, SIZE.height, 'flipHorizontal'), { x: 70, y: 5, width: 20, height: 10 })
  assert.deepEqual(transformRect(rect, SIZE.width, SIZE.height, 'flipVertical'), { x: 10, y: 35, width: 20, height: 10 })
})

test('the whole picture stays the whole picture', () => {
  const whole = { x: 0, y: 0, width: SIZE.width, height: SIZE.height }
  for (const op of IMAGE_TRANSFORMS) {
    const size = transformedSize(SIZE.width, SIZE.height, op)
    assert.deepEqual(transformRect(whole, SIZE.width, SIZE.height, op), { x: 0, y: 0, ...size }, op)
  }
})

test('undoing a change, or four quarter turns, returns the same area', () => {
  const back = (first: ImageTransform, second: ImageTransform) => {
    const size = transformedSize(SIZE.width, SIZE.height, first)
    return transformRect(transformRect(rect, SIZE.width, SIZE.height, first), size.width, size.height, second)
  }
  assert.deepEqual(back('rotateRight', 'rotateLeft'), rect)
  assert.deepEqual(back('rotateLeft', 'rotateRight'), rect)
  assert.deepEqual(back('flipHorizontal', 'flipHorizontal'), rect)
  assert.deepEqual(back('flipVertical', 'flipVertical'), rect)
  let turned = rect, width = SIZE.width, height = SIZE.height
  for (let turn = 0; turn < 4; turn += 1) {
    turned = transformRect(turned, width, height, 'rotateRight');[width, height] = [height, width]
  }
  assert.deepEqual(turned, rect)
})

test('the pixels land where the selected area says they do', () => {
  const image = { naturalWidth: SIZE.width, naturalHeight: SIZE.height } as HTMLImageElement
  for (const op of IMAGE_TRANSFORMS) {
    const { canvas, drawn } = fakeCanvas()
    const result = withFakeDocument(canvas, () => transformImage(image, op)) as unknown as { width: number; height: number }
    const size = transformedSize(SIZE.width, SIZE.height, op)
    assert.deepEqual({ width: result.width, height: result.height }, size, `${op} canvas size`)
    const [origin, far] = drawn[0]
    // The picture fills the new canvas exactly: its two opposite corners are the canvas corners.
    assert.deepEqual([Math.min(origin.x, far.x), Math.min(origin.y, far.y)], [0, 0], `${op} starts at the corner`)
    assert.deepEqual([Math.max(origin.x, far.x), Math.max(origin.y, far.y)], [size.width, size.height], `${op} fills the canvas`)
  }
})

test('a marked corner of the selection moves with the canvas drawing', () => {
  const image = { naturalWidth: SIZE.width, naturalHeight: SIZE.height } as HTMLImageElement
  for (const op of IMAGE_TRANSFORMS) {
    const made = fakeCanvas()
    withFakeDocument(made.canvas, () => transformImage(image, op))
    const first = made.at(rect.x, rect.y), second = made.at(rect.x + rect.width, rect.y + rect.height)
    const mapped = transformRect(rect, SIZE.width, SIZE.height, op)
    assert.deepEqual({ x: Math.min(first.x, second.x), y: Math.min(first.y, second.y) }, { x: mapped.x, y: mapped.y }, `${op} corner`)
    assert.deepEqual({ width: Math.abs(first.x - second.x), height: Math.abs(first.y - second.y) },
      { width: mapped.width, height: mapped.height }, `${op} extent`)
  }
})
