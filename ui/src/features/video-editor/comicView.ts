// Portrait comic pages for one montage. Each clip is one panel, in order.
// The layout is deterministic: the same clips always produce the same pages.

export const PAGE_W = 1000
export const PAGE_H = 1414
export const MARGIN = 48
export const GUTTER = 18
export const TIERS_PER_PAGE = 3

export interface ComicLayoutClip {
  id: string
  duration: number
  width: number
  height: number
  focusX?: number
  focusY?: number
}

export interface ComicPanelBox {
  id: string
  span: number
  x: number
  y: number
  w: number
  h: number
  focusX: number
  focusY: number
  splash: boolean
}

export interface ComicTier {
  y: number
  h: number
  panels: ComicPanelBox[]
}

export interface ComicPage {
  index: number
  width: number
  height: number
  columns: number
  tiers: ComicTier[]
}

interface PlannedPanel {
  id: string
  span: number
  splash: boolean
  focusX: number
  focusY: number
}

/** 3 columns when vertical frames are the majority (a square counts as vertical). */
export function columnCount(clips: ComicLayoutClip[]): number {
  if (!clips.length) return 3
  const vertical = clips.filter(clip => clip.height >= clip.width || !clip.width || !clip.height).length
  return vertical * 2 >= clips.length ? 3 : 2
}

export function layoutComic(clips: ComicLayoutClip[]): ComicPage[] {
  if (!clips.length) return []
  const columns = columnCount(clips)
  return placePages(packRows(planPanels(clips, columns), columns), columns)
}

function planPanels(clips: ComicLayoutClip[], columns: number): PlannedPanel[] {
  const durations = clips.map(clip => Math.max(0, clip.duration))
  const middle = median(durations)
  const splashAt = durations.reduce((best, duration, index) => duration > durations[best] ? index : best, 0)
  return clips.map((clip, index) => ({
    id: clip.id,
    span: index === splashAt ? columns : spanFor(durations[index], middle, columns),
    splash: index === splashAt,
    focusX: clampFocus(clip.focusX),
    focusY: clampFocus(clip.focusY),
  }))
}

function spanFor(duration: number, middle: number, columns: number): number {
  if (middle > 0 && duration >= middle * 1.6) return Math.min(2, columns)
  return 1
}

function median(values: number[]): number {
  if (!values.length) return 0
  const sorted = [...values].sort((left, right) => left - right)
  const mid = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 1) return sorted[mid]
  return (sorted[mid - 1] + sorted[mid]) / 2
}

function clampFocus(value: number | undefined): number {
  if (typeof value !== 'number' || Number.isNaN(value)) return 50
  return Math.min(100, Math.max(0, value))
}

/** Fill every tier. A panel that does not fit shrinks; a splash never does. */
function packRows(planned: PlannedPanel[], columns: number): PlannedPanel[][] {
  const rows: PlannedPanel[][] = []
  let row: PlannedPanel[] = []
  let used = 0
  const close = () => { rows.push(row); row = []; used = 0 }
  for (const original of planned) {
    let item = original
    const room = columns - used
    if (item.span > room) item = fitPanel(item, row, room, close)
    row.push(item)
    used += item.span
    if (used >= columns) close()
  }
  if (row.length) rows.push(row)
  return rows
}

function fitPanel(item: PlannedPanel, row: PlannedPanel[], room: number, close: () => void): PlannedPanel {
  if (item.splash) {
    if (row.length) stretchLast(row, room)
    close()
    return item
  }
  if (room > 0) return { ...item, span: room }
  close()
  return item
}

function stretchLast(row: PlannedPanel[], room: number): void {
  const last = row[row.length - 1]
  row[row.length - 1] = { ...last, span: last.span + room }
}

function placePages(rows: PlannedPanel[][], columns: number): ComicPage[] {
  const pages: ComicPage[] = []
  for (let start = 0; start < rows.length; start += TIERS_PER_PAGE) {
    pages.push(placePage(rows.slice(start, start + TIERS_PER_PAGE), pages.length, columns))
  }
  return pages
}

function placePage(rows: PlannedPanel[][], index: number, columns: number): ComicPage {
  const contentW = PAGE_W - 2 * MARGIN
  const contentH = PAGE_H - 2 * MARGIN
  const tierH = round3((contentH - (TIERS_PER_PAGE - 1) * GUTTER) / TIERS_PER_PAGE)
  const unit = (contentW - (columns - 1) * GUTTER) / columns
  return {
    index, width: PAGE_W, height: PAGE_H, columns,
    tiers: rows.map((items, tierIndex) => placeTier(items, tierIndex, tierH, unit)),
  }
}

function placeTier(items: PlannedPanel[], tierIndex: number, tierH: number, unit: number): ComicTier {
  let x = MARGIN
  const y = round3(MARGIN + tierIndex * (tierH + GUTTER))
  const panels = items.map(item => {
    const panel = { ...item, x: round3(x), y, w: round3(item.span * unit + (item.span - 1) * GUTTER), h: tierH }
    x += panel.w + GUTTER
    return panel
  })
  return { y, h: tierH, panels }
}

function round3(value: number): number {
  return Math.round(value * 1000) / 1000
}
