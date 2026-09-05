import assert from 'node:assert/strict'
import test from 'node:test'
import {
  buildInfinitePanoramaPrompt,
  createSeamBandRects,
  createTripleTileLayout,
  createTripleTilePreviewPlacements,
} from '../src/lib/panoramaLoop.ts'

test('triple tile layout places three equal tiles and two join bands', () => {
  const layout = createTripleTileLayout(1000, 500, 80)
  assert.deepEqual(layout.canvas, { x: 0, y: 0, width: 3000, height: 500 })
  assert.deepEqual(layout.tiles.map(tile => [tile.x, tile.width]), [[0, 1000], [1000, 1000], [2000, 1000]])
  assert.deepEqual(layout.seamBands.map(band => [band.x, band.width]), [[960, 80], [1960, 80]])
})

test('preview placements and seam helper share the same canonical coordinates', () => {
  const placements = createTripleTilePreviewPlacements(640, 360)
  const bands = createSeamBandRects(640, 360, 64)
  assert.equal(placements.length, 3)
  assert.deepEqual(placements.map(tile => tile.x), [0, 640, 1280])
  assert.deepEqual(bands.map(band => band.x), [608, 1248])
  assert.ok(bands.every(band => band.height === 360))
})

test('invalid dimensions fall back to a safe positive geometry', () => {
  const layout = createTripleTileLayout(Number.NaN, 0)
  assert.deepEqual(layout.canvas, { x: 0, y: 0, width: 3, height: 1 })
  assert.equal(layout.tiles.length, 3)
})

test('infinite panorama prompt states edge continuity and optional occluder', () => {
  const prompt = buildInfinitePanoramaPrompt({
    subject: 'a moonlit train station',
    style: 'cinematic anime background',
    foregroundOccluder: 'lamp post',
  })
  assert.match(prompt, /seamless horizontally looping panorama/)
  assert.match(prompt, /left and right edges continue naturally/)
  assert.match(prompt, /lamp post/)
  assert.match(prompt, /no frame, border, text/)
})
