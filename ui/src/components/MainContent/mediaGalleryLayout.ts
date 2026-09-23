import type { OutputFile } from '../../types'

/** The three gallery layouts share one geometry model: a vertical stack of
 *  blocks (rows), each holding one or more cells. Every size is computed from
 *  the item's known aspect and the viewport before anything loads, so the
 *  virtualizer never positions a row from a guess and no row can be taller
 *  than the screen that shows it. */
export type GalleryLayoutView = 'feed' | 'grid' | 'masonry'

export interface GalleryCell {
  index: number
  left: number
  width: number
  height: number
}

export interface GalleryBlock {
  top: number
  height: number
  cells: GalleryCell[]
}

export interface GalleryLayout {
  view: GalleryLayoutView
  width: number
  /** Changes whenever rows are regrouped (view, width or grid columns), so an
   *  anchor knows its offset inside the old row no longer applies. */
  shape: string
  blocks: GalleryBlock[]
  height: number
  /** Block that holds each output index. */
  blockOf: number[]
}

type SizedOutput = Pick<OutputFile, 'type' | 'width' | 'height'>

export const FEED_GAP = 12
/** Card chrome around the media box: two-line summary plus one action row. */
export const FEED_INFO_BAR_HEIGHT = 100
/** `border-2` on the top and bottom edges. */
export const FEED_CARD_BORDER = 4
const FEED_AUDIO_MEDIA_HEIGHT = 208
const MIN_MEDIA_HEIGHT = 96
const PHONE_WIDTH = 640

const FALLBACK_ASPECT = 16 / 9
const COMIC_ASPECT = 3 / 4
const MIN_ASPECT = 0.4
const MAX_ASPECT = 3

/** Width ÷ height, from the listing when known. Extreme panoramas and strips
 *  are clamped so a single item cannot collapse a row to a sliver. */
export function galleryAspect(file: SizedOutput): number {
  const known = file.width && file.height && file.width > 0 && file.height > 0 ? file.width / file.height : null
  const aspect = known ?? (file.type === 'comic' ? COMIC_ASPECT : FALLBACK_ASPECT)
  return Math.min(MAX_ASPECT, Math.max(MIN_ASPECT, aspect))
}

/** Mosaic cells for audio and 3D carry a label or a small render, not a
 *  picture worth a wide slot, so they stay square and compact. */
export function mosaicAspect(file: SizedOutput): number {
  return file.type === 'audio' || file.type === 'model3d' ? 1 : galleryAspect(file)
}

export function galleryGap(view: GalleryLayoutView, width: number): number {
  if (view === 'feed') return FEED_GAP
  return width < PHONE_WIDTH ? 4 : 12
}

/** Height of the media box inside a one-up card. */
export function feedMediaHeight(file: SizedOutput, width: number, viewportHeight: number): number {
  const cap = Math.max(MIN_MEDIA_HEIGHT, Math.floor(viewportHeight - FEED_INFO_BAR_HEIGHT - FEED_CARD_BORDER))
  if (file.type === 'audio') return Math.min(FEED_AUDIO_MEDIA_HEIGHT, cap)
  const innerWidth = Math.max(1, width - FEED_CARD_BORDER)
  return Math.max(MIN_MEDIA_HEIGHT, Math.min(cap, Math.round(innerWidth / galleryAspect(file))))
}

export function feedCardHeight(file: SizedOutput, width: number, viewportHeight: number): number {
  return feedMediaHeight(file, width, viewportHeight) + FEED_INFO_BAR_HEIGHT + FEED_CARD_BORDER
}

function stack(view: GalleryLayoutView, width: number, rows: Array<{ height: number; cells: GalleryCell[] }>, count: number, variant = ''): GalleryLayout {
  const gap = galleryGap(view, width)
  const blocks: GalleryBlock[] = []
  const blockOf = new Array<number>(count)
  let top = 0
  for (const row of rows) {
    for (const cell of row.cells) blockOf[cell.index] = blocks.length
    blocks.push({ top, height: row.height, cells: row.cells })
    top += row.height + gap
  }
  return { view, width, shape: `${view}:${width}:${variant}`, blocks, height: blocks.length ? top - gap : 0, blockOf }
}

function feedLayout(outputs: SizedOutput[], width: number, viewportHeight: number): GalleryLayout {
  const cellWidth = Math.max(1, Math.floor(width))
  return stack('feed', width, outputs.map((file, index) => {
    const height = feedCardHeight(file, cellWidth, viewportHeight)
    return { height, cells: [{ index, left: 0, width: cellWidth, height }] }
  }), outputs.length)
}

/** Columns for the square grid. A phone may override the width-derived count
 *  with a pinch; wider screens always follow their width. */
export function gridColumns(width: number, preferred?: number | null): number {
  if (preferred && width < PHONE_WIDTH) return Math.max(1, Math.round(preferred))
  const gap = galleryGap('grid', width)
  const minTile = width < PHONE_WIDTH ? 110 : 190
  return Math.max(1, Math.floor((width + gap) / (minTile + gap)))
}

function gridLayout(outputs: SizedOutput[], width: number, viewportHeight: number, preferred?: number | null): GalleryLayout {
  const gap = galleryGap('grid', width)
  const columns = gridColumns(width, preferred)
  const tile = Math.max(1, Math.floor((width - gap * (columns - 1)) / columns))
  const height = Math.min(tile, Math.max(MIN_MEDIA_HEIGHT, Math.floor(viewportHeight)))
  const rows: Array<{ height: number; cells: GalleryCell[] }> = []
  for (let start = 0; start < outputs.length; start += columns) {
    const cells: GalleryCell[] = []
    for (let column = 0; column < columns && start + column < outputs.length; column++) {
      cells.push({ index: start + column, left: column * (tile + gap), width: tile, height })
    }
    rows.push({ height, cells })
  }
  return stack('grid', width, rows, outputs.length, String(columns))
}

/** Justified rows: every item keeps its aspect, each full row spans the width
 *  exactly, and the last row stays at the target height instead of stretching. */
function masonryLayout(outputs: SizedOutput[], width: number, viewportHeight: number): GalleryLayout {
  const gap = galleryGap('masonry', width)
  const target = width < PHONE_WIDTH ? 150 : 220
  const maxHeight = Math.max(MIN_MEDIA_HEIGHT, Math.min(Math.round(target * 1.6), Math.floor(viewportHeight)))
  const rows: Array<{ height: number; cells: GalleryCell[] }> = []
  let pending: number[] = []
  let aspectSum = 0

  const place = (indices: number[], height: number, justify = true) => {
    const cells: GalleryCell[] = []
    let x = 0
    for (const index of indices) {
      const exact = mosaicAspect(outputs[index]) * height
      const left = Math.round(x)
      const right = Math.round(x + exact)
      cells.push({ index, left, width: Math.max(1, right - left), height })
      x += exact + gap
    }
    // Absorb rounding so a justified row ends exactly on the right edge.
    const last = cells[cells.length - 1]
    if (justify && last) last.width = Math.max(1, width - last.left)
    rows.push({ height, cells })
  }

  const rowHeight = (count: number, sum: number) => (width - gap * (count - 1)) / sum

  outputs.forEach((file, index) => {
    const aspect = mosaicAspect(file)
    pending.push(index)
    aspectSum += aspect
    if (aspectSum * target < width - gap * (pending.length - 1)) return
    // The row is full. Close it with this item (shorter than target) or
    // without it (taller), whichever lands nearer the target height.
    const withItem = rowHeight(pending.length, aspectSum)
    const withoutItem = pending.length > 1 ? rowHeight(pending.length - 1, aspectSum - aspect) : Infinity
    if (withoutItem <= maxHeight && Math.abs(withoutItem - target) < Math.abs(withItem - target)) {
      place(pending.slice(0, -1), Math.round(withoutItem))
      pending = [index]
      aspectSum = aspect
      return
    }
    place(pending, Math.max(1, Math.min(maxHeight, Math.round(withItem))))
    pending = []
    aspectSum = 0
  })
  if (pending.length) {
    const usable = width - gap * (pending.length - 1)
    place(pending, Math.max(1, Math.min(target, maxHeight, Math.floor(usable / aspectSum))), false)
  }
  return stack('masonry', width, rows, outputs.length)
}

export function buildGalleryLayout(
  view: GalleryLayoutView,
  outputs: SizedOutput[],
  width: number,
  viewportHeight: number,
  options: { gridColumns?: number | null } = {},
): GalleryLayout {
  const usableWidth = Math.max(1, Math.floor(width))
  if (view === 'grid') return gridLayout(outputs, usableWidth, viewportHeight, options.gridColumns)
  if (view === 'masonry') return masonryLayout(outputs, usableWidth, viewportHeight)
  return feedLayout(outputs, usableWidth, viewportHeight)
}

/** First block whose bottom edge is below `offset`. */
export function blockAt(layout: GalleryLayout, offset: number): number {
  const { blocks } = layout
  let lo = 0
  let hi = blocks.length - 1
  if (hi < 0) return 0
  while (lo < hi) {
    const mid = (lo + hi) >>> 1
    if (blocks[mid].top + blocks[mid].height <= offset) lo = mid + 1
    else hi = mid
  }
  return lo
}

export interface BlockRange {
  first: number
  last: number
}

/** Blocks intersecting the viewport, plus `overscan` pixels on both sides. */
export function visibleBlocks(layout: GalleryLayout, offset: number, viewportHeight: number, overscan: number): BlockRange {
  if (!layout.blocks.length) return { first: 0, last: -1 }
  const first = blockAt(layout, Math.max(0, offset - overscan))
  const end = offset + viewportHeight + overscan
  let last = first
  while (last + 1 < layout.blocks.length && layout.blocks[last + 1].top < end) last += 1
  return { first, last }
}

export interface GalleryAnchor {
  /** Output name, so the anchor survives inserts above it. */
  name: string
  /** Distance scrolled past the top of that item's block. */
  within: number
}

export function anchorAt(layout: GalleryLayout, outputs: Pick<OutputFile, 'name'>[], offset: number): GalleryAnchor | null {
  if (!layout.blocks.length) return null
  const block = layout.blocks[blockAt(layout, offset)]
  const cell = block.cells[0]
  const file = cell && outputs[cell.index]
  return file ? { name: file.name, within: Math.max(0, offset - block.top) } : null
}

/** Scroll offset that puts `anchor` back where it was. When the layout
 *  changed shape (another view, another width) the anchored item is aligned
 *  to the top of its new row instead of an offset that no longer means much. */
export function anchorOffset(
  layout: GalleryLayout,
  outputs: Pick<OutputFile, 'name'>[],
  anchor: GalleryAnchor,
  keepWithin: boolean,
): number | null {
  const index = outputs.findIndex(file => file.name === anchor.name)
  if (index < 0) return null
  const block = layout.blocks[layout.blockOf[index]]
  if (!block) return null
  return block.top + (keepWithin ? Math.min(anchor.within, Math.max(0, block.height - 1)) : 0)
}

export type GalleryDirection = 'up' | 'down' | 'left' | 'right'

/** The item a keyboard step lands on. Left/right walk the list order; up/down
 *  move one row and keep the column closest to the current item. */
export function neighborIndex(layout: GalleryLayout, index: number, direction: GalleryDirection): number {
  const count = layout.blockOf.length
  if (!count) return index
  const current = Math.min(Math.max(0, index), count - 1)
  if (direction === 'left') return Math.max(0, current - 1)
  if (direction === 'right') return Math.min(count - 1, current + 1)
  const row = layout.blockOf[current]
  const target = layout.blocks[row + (direction === 'down' ? 1 : -1)]
  if (!target) return current
  const cell = layout.blocks[row].cells.find(item => item.index === current)
  const center = cell ? cell.left + cell.width / 2 : 0
  let best = target.cells[0]
  for (const candidate of target.cells) {
    if (Math.abs(candidate.left + candidate.width / 2 - center) < Math.abs(best.left + best.width / 2 - center)) best = candidate
  }
  return best.index
}
