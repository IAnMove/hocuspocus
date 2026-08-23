import assert from 'node:assert/strict'
import test from 'node:test'

import { mapDirectorClipImages } from '../src/lib/directorClipImages.ts'

test('recovery keeps original indices when failed image slots are omitted', () => {
  const images = mapDirectorClipImages(['', 'b.png', '', 'd.png'])
  assert.deepEqual(images.map(image => image.clipIndex), [1, 3])
  assert.deepEqual(images.map(image => image.filename), ['b.png', 'd.png'])
})

test('recovery prefers a stable shot identity when an entry supplies one', () => {
  const images = mapDirectorClipImages([
    { shot_id: 'shot-b', filename: 'b.png' },
    { shot_id: 'shot-d', filename: 'd.png' },
  ], [
    { shot_id: 'shot-a', image_prompt: 'A' },
    { shot_id: 'shot-b', image_prompt: 'B' },
    { shot_id: 'shot-c', image_prompt: 'C' },
    { shot_id: 'shot-d', image_prompt: 'D' },
  ])
  assert.deepEqual(images.map(image => image.clipIndex), [1, 3])
  assert.deepEqual(images.map(image => image.shotId), ['shot-b', 'shot-d'])
})

test('stable shot identity honors explicit plan slots and skips null entries', () => {
  const images = mapDirectorClipImages([
    null,
    { shotId: 'shot-d', filename: 'd.png', clipIndex: -1 },
  ], [
    { shotId: 'shot-d', index: 3, image_prompt: 'D' },
  ])
  assert.deepEqual(images.map(image => image.clipIndex), [3])
  assert.deepEqual(images.map(image => image.prompt), ['D'])
})
