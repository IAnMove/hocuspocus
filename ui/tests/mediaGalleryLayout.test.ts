import assert from 'node:assert/strict'
import test from 'node:test'
import {
  FEED_CARD_BORDER,
  FEED_GAP,
  FEED_INFO_BAR_HEIGHT,
  anchorAt,
  anchorOffset,
  blockAt,
  buildGalleryLayout,
  feedMediaHeight,
  galleryAspect,
  gridColumns,
  mosaicAspect,
  visibleBlocks,
  type GalleryLayout,
} from '../src/components/MainContent/mediaGalleryLayout.ts'
import type { OutputFile } from '../src/types/index.ts'

type Item = Pick<OutputFile, 'name' | 'type' | 'width' | 'height'>

const kinds: Item['type'][] = ['image', 'video', 'audio', 'scene', 'comic', 'model3d']
function library(count: number): Item[] {
  return Array.from({ length: count }, (_, index) => {
    const type = kinds[index % kinds.length]
    const sized = type === 'image' || (type === 'video' && index % 4 !== 1)
    const portrait = index % 3 === 0
    return {
      name: `item-${index}`,
      type,
      ...(sized ? { width: portrait ? 480 : 1600, height: portrait ? 1600 : 480 } : {}),
    }
  })
}

function assertStacked(layout: GalleryLayout, gap: number) {
  let expected = 0
  for (const block of layout.blocks) {
    assert.equal(block.top, expected, 'blocks are contiguous: no overlap and no stray gap')
    for (const cell of block.cells) assert.ok(cell.height <= block.height)
    expected = block.top + block.height + gap
  }
  assert.equal(layout.height, layout.blocks.length ? expected - gap : 0)
  for (let index = 0; index < layout.blockOf.length; index++) {
    assert.ok(layout.blocks[layout.blockOf[index]].cells.some(cell => cell.index === index), `item ${index} is placed once`)
  }
}

for (const [width, height] of [[386, 578], [1156, 582], [1796, 942], [812, 250]] as const) {
  test(`feed rows never exceed the ${width}x${height} viewport and stack exactly`, () => {
    const items = library(60)
    const layout = buildGalleryLayout('feed', items, width, height)
    assertStacked(layout, FEED_GAP)
    for (const block of layout.blocks) {
      const file = items[block.cells[0].index]
      if (height >= 96 + FEED_INFO_BAR_HEIGHT + FEED_CARD_BORDER) assert.ok(block.height <= height, `${file.name} ${block.height} > ${height}`)
      assert.equal(block.cells[0].width, width)
    }
  })
}

test('feed media keeps the real aspect until the viewport caps it', () => {
  const landscape = { type: 'image' as const, width: 1600, height: 900 }
  assert.equal(feedMediaHeight(landscape, 804, 900), 450)
  const portrait = { type: 'image' as const, width: 480, height: 1600 }
  assert.equal(feedMediaHeight(portrait, 390, 602), 602 - FEED_INFO_BAR_HEIGHT - FEED_CARD_BORDER)
  assert.equal(feedMediaHeight({ type: 'audio' }, 1200, 900), 208)
  assert.equal(galleryAspect({ type: 'video' }), 16 / 9)
  assert.equal(galleryAspect({ type: 'comic' }), 3 / 4)
  assert.equal(galleryAspect({ type: 'image', width: 9000, height: 100 }), 3)
  assert.equal(mosaicAspect({ type: 'audio' }), 1)
  assert.equal(mosaicAspect({ type: 'image', width: 480, height: 1600 }), 0.4)
})

test('grid is three columns on a phone and square tiles within the width', () => {
  assert.equal(gridColumns(378), 3)
  assert.equal(gridColumns(1236), 6)
  for (const width of [378, 1236]) {
    const layout = buildGalleryLayout('grid', library(40), width, 600)
    assertStacked(layout, width < 640 ? 4 : 12)
    for (const block of layout.blocks) for (const cell of block.cells) {
      assert.equal(cell.width, cell.height)
      assert.ok(cell.left >= 0 && cell.left + cell.width <= width)
    }
  }
})

for (const width of [378, 1236]) {
  test(`mosaic rows at ${width}px are justified and keep each aspect`, () => {
    const items = [...library(50), { name: 'pano', type: 'image' as const, width: 8000, height: 1000 }, ...library(7)]
    const layout = buildGalleryLayout('masonry', items, width, 600)
    const gap = width < 640 ? 4 : 12
    assertStacked(layout, gap)
    layout.blocks.forEach((block, row) => {
      const cells = block.cells
      for (let index = 1; index < cells.length; index++) {
        assert.equal(cells[index].left, cells[index - 1].left + cells[index - 1].width + gap, 'constant gutter')
      }
      for (const cell of cells) {
        const aspect = mosaicAspect(items[cell.index])
        assert.ok(Math.abs(cell.width - aspect * cell.height) <= 3, `cell ${cell.index} keeps its aspect`)
      }
      assert.ok(block.height >= 60, 'a panorama cannot collapse a row')
      assert.ok(block.height <= 600)
      if (row < layout.blocks.length - 1) assert.equal(cells.at(-1)!.left + cells.at(-1)!.width, width, 'full rows end on the edge')
      else assert.ok(cells.at(-1)!.left + cells.at(-1)!.width <= width)
    })
  })
}

test('visible range covers exactly the blocks crossing the viewport', () => {
  const layout = buildGalleryLayout('feed', library(30), 386, 578)
  const offset = layout.blocks[5].top + 10
  assert.equal(blockAt(layout, offset), 5)
  const range = visibleBlocks(layout, offset, 578, 0)
  assert.equal(range.first, 5)
  assert.ok(layout.blocks[range.last].top < offset + 578)
  assert.ok(range.last + 1 >= layout.blocks.length || layout.blocks[range.last + 1].top >= offset + 578)
  assert.deepEqual(visibleBlocks(buildGalleryLayout('feed', [], 386, 578), 0, 578, 0), { first: 0, last: -1 })
})

test('anchor follows the same item across inserts and view changes', () => {
  const items = library(40)
  const feed = buildGalleryLayout('feed', items, 386, 578)
  const offset = feed.blocks[12].top + 37
  const anchor = anchorAt(feed, items, offset)!
  assert.deepEqual(anchor, { name: 'item-12', within: 37 })

  const prepended = [{ name: 'new-1', type: 'image' as const, width: 1000, height: 1000 }, ...items]
  const shifted = buildGalleryLayout('feed', prepended, 386, 578)
  assert.equal(anchorOffset(shifted, prepended, anchor, true), shifted.blocks[13].top + 37)

  const grid = buildGalleryLayout('grid', items, 378, 578)
  assert.equal(anchorOffset(grid, items, anchor, false), grid.blocks[4].top)
  assert.equal(anchorOffset(grid, items, { name: 'gone', within: 0 }, false), null)
})
